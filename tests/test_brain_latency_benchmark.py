from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from metis_model1.brain_latency_benchmark import (
    counterbalanced_schedule_sha256,
    observation_from_terminal,
    seal_latency_receipt,
    selection_roster_sha256,
    verify_latency_receipt,
    write_latency_receipt,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_sha256

SHAPE_CONTRACT = {
    "endpoint": "demo.a_b_test",
    "take": {"mode": "count", "value": 24},
    "order_field": "publication_date",
    "order_direction": "descending",
    "response": "response.expanded",
}


def _sha(label: str) -> str:
    return canonical_sha256(label)


def _metrics(*, prefix: bool) -> dict[str, int | float | str | bool]:
    generation_ms = 100 if prefix else 180
    return {
        "worker_load_ms": 0,
        "worker_request_ms": 110 if prefix else 190,
        "cache_prepare_ms": 2,
        "generation_ms": generation_ms,
        "tokenization_ms": 4,
        "time_to_first_token_ms": 40 if prefix else 120,
        "decode_after_first_token_ms": 45,
        "generation_residual_ms": 15,
        "worker_residual_ms": 4,
        "model_lock_queue_ms": 0,
        "prompt_tokens": 80,
        "uncached_prompt_tokens": 20 if prefix else 80,
        "generation_tokens": 8,
        "cached_tokens": 60 if prefix else 0,
        "cache_hit": prefix,
        "cache_mode": "prefix" if prefix else "disabled",
        "prompt_tps": 2_000.0 if prefix else 80_000.0 / 120.0,
        "generation_tps": 8_000.0 / 45.0,
        "finish_reason": "stop",
        "peak_metal_gb": 4.0,
    }


def _identity() -> dict[str, object]:
    event_roster_sha256 = canonical_sha256(
        [
            "turn.accepted",
            "retrieval.started",
            "retrieval.completed",
            "catalog.auto_selected",
            "inference.started",
            "inference.completed",
            "compile.started",
            "compile.completed",
            "terminal",
        ]
    )
    preflight_common = {
        "request_sha256": _sha("request"),
        "source_sha256": bytes_sha256(
            _terminal(prefix=True)["proposal"]["source"].encode()  # type: ignore[index,union-attr]
        ),
        "compiled_endpoint_sha256": _sha("compiled"),
        "grounding_selections_sha256": selection_roster_sha256(
            [{"catalog": "play-demo.video", "field": "mood", "literal": "Romantico"}]
        ),
        "shape_contract_sha256": canonical_sha256(SHAPE_CONTRACT),
        "processing_route": "direct",
        "intent_compiler_sha256": canonical_sha256(
            {"processing_route": "direct", "identity": None}
        ),
        "event_roster_sha256": event_roster_sha256,
        "model_revision": "qwen-qualified-27b",
        "adapter_sha256": _sha("adapter"),
        "worker_sha256": _sha("worker"),
        "prompt_prefix_sha256": _sha("prefix"),
    }
    decode_preflights = [{"arm": arm, **preflight_common} for arm in ("direct", "prefix")]
    return {
        "benchmark_id": "play-demo-latency-v1",
        "case_sha256": _sha("case"),
        "model1_commit": "11" * 20,
        "model1_tree": "22" * 20,
        "seed": 17,
        "pairs": 6,
        "arm_order": ["direct", "prefix"],
        "schedule_sha256": counterbalanced_schedule_sha256(
            pairs=5 + 1, arm_order=["direct", "prefix"]
        ),
        "model_revision": "qwen-qualified-27b",
        "adapter_sha256": _sha("adapter"),
        "worker_sha256": _sha("worker"),
        "prompt_prefix_sha256": _sha("prefix"),
        "expected_prefix_tokens": 60,
        "retrieval_prewarm_ms": 120,
        "decode_preflight_count": 2,
        "decode_preflights": decode_preflights,
        "decode_preflight_sha256": canonical_sha256(decode_preflights),
        "decode_preflight_source_sha256": preflight_common["source_sha256"],
        "decode_preflight_compiled_endpoint_sha256": _sha("compiled"),
        "tenant_commit": "44aa8ec170003b3822db71cb9443c8e7db9e3dd0",
        "tenant_tree": "tree-play-demo",
        "tenant_roster_sha256": _sha("roster"),
        "tenant_status_sha256": _sha("status"),
        "target_sha256": _sha("target"),
        "context_revision": _sha("context"),
        "semantic_source_revision": _sha("semantic"),
        "toolchain_binding": _sha("toolchain"),
        "request_sha256": _sha("request"),
        "expected_grounding_selections_sha256": selection_roster_sha256(
            [{"catalog": "play-demo.video", "field": "mood", "literal": "Romantico"}]
        ),
        "expected_shape_contract_sha256": canonical_sha256(SHAPE_CONTRACT),
        "expected_processing_route": "direct",
        "expected_intent_compiler_sha256": canonical_sha256(
            {"processing_route": "direct", "identity": None}
        ),
    }


def _runtime_identity() -> dict[str, str]:
    return {
        "model_revision": "qwen-qualified-27b",
        "adapter_sha256": _sha("adapter"),
        "worker_sha256": _sha("worker"),
        "prompt_prefix_sha256": _sha("prefix"),
    }


def _tenant_guard() -> dict[str, str]:
    return {
        "commit": "44aa8ec170003b3822db71cb9443c8e7db9e3dd0",
        "tree": "tree-play-demo",
        "status_sha256": _sha("status"),
        "roster_sha256": _sha("roster"),
        "target_sha256": _sha("target"),
    }


def _terminal(
    *, prefix: bool, source: str | None = None, flash_retry: bool = False
) -> dict[str, object]:
    if source is None:
        source = """metis 0.43
endpoint demo.a_b_test {
  take 24 from @play-demo.video {
    include where {
      @mood is "Romantico"
    }
    order by @publication_date descending
    return response.expanded
  }
}
"""
    identity: dict[str, object] = {
        "model_revision": "qwen-qualified-27b",
        "adapter_sha256": _sha("adapter"),
        "context_revision": _sha("context"),
        "semantic_source_revision": _sha("semantic"),
        "toolchain_binding": _sha("toolchain"),
        "generation_strategy": "model",
        "generation_metrics": _metrics(prefix=prefix),
    }
    if flash_retry:
        identity["intent_compiler"] = {
            "model_revision": "flash-qualified",
            "schema_sha256": _sha("flash-schema"),
            "decoder": "schema-constrained",
        }
    return {
        "schema_version": 2,
        "turn_id": "turn-fixture",
        "status": "completed",
        "outcome": "proposed",
        "route": "local",
        "proposal": {"source": source, "source_sha256": bytes_sha256(source.encode())},
        "identity": identity,
        "grounding": {
            "status": "resolved",
            "catalogs": ["play-demo.video"],
            "candidates": [],
            "unresolved": [],
            "output_contract": {
                "take": {"mode": "count", "value": 24, "source": "operator_confirmed"},
                "fallback": {"mode": "none"},
            },
            "selections": [
                {
                    "catalog": "play-demo.video",
                    "field": "mood",
                    "type": "keyword",
                    "modifiers": [],
                    "domain": {"kind": "inline", "size": 1},
                    "literal": "Romantico",
                }
            ],
        },
        "validation": {
            "status": "ok",
            "diagnostics": [],
            "attempts": 1,
            "compiler_receipt_sha256": _sha("receipt"),
            "compiled_endpoint_sha256": _sha("compiled"),
        },
        "claims": {"compile_clean": True, "semantic_grounded": True, "tenant_modified": False},
    }


def _events(*, pair: int, prefix: bool = False) -> list[dict[str, object]]:
    del pair

    def event(name: str, sequence: int, **metrics: object) -> dict[str, object]:
        return {
            "event": name,
            "data": {
                "schema_version": 1,
                "turn_id": "turn-fixture",
                "sequence": sequence,
                "phase": name.replace(".", "_"),
                "label": "Fixture verificata",
                **metrics,
            },
        }

    return [
        event("turn.accepted", 1),
        event("retrieval.started", 2),
        event("retrieval.completed", 3, duration_ms=12),
        event("catalog.auto_selected", 4),
        event("inference.started", 5),
        event("heartbeat", 6, elapsed_ms=4_000),
        event("inference.completed", 7, duration_ms=120 if prefix else 200),
        event("compile.started", 8),
        event("compile.completed", 9, duration_ms=9),
        {
            "event": "terminal",
            "data": {
                "schema_version": 1,
                "turn_id": "turn-fixture",
                "sequence": 10,
                "phase": "terminal",
                "label": "Turn terminato",
            },
        },
    ]


def _flash_retry_events(*, prefix: bool = False) -> list[dict[str, object]]:
    direct = _events(pair=1, prefix=prefix)
    prefix_events = direct[:3]
    suffix_events = direct[3:]
    inserted = [
        {
            "event": "intent.started",
            "data": {
                "schema_version": 1,
                "turn_id": "turn-fixture",
                "sequence": 4,
                "phase": "intent_started",
                "label": "Interpreto i requisiti non risolti",
            },
        },
        {
            "event": "intent.completed",
            "data": {
                "schema_version": 1,
                "turn_id": "turn-fixture",
                "sequence": 5,
                "phase": "intent_completed",
                "label": "Interpretazione delimitata pronta",
                "duration_ms": 7,
            },
        },
        {
            "event": "retrieval.started",
            "data": {
                "schema_version": 1,
                "turn_id": "turn-fixture",
                "sequence": 6,
                "phase": "retrieval_retry_started",
                "label": "Riprovo il grounding sui requisiti esatti",
            },
        },
        {
            "event": "retrieval.completed",
            "data": {
                "schema_version": 1,
                "turn_id": "turn-fixture",
                "sequence": 7,
                "phase": "retrieval_retry_completed",
                "label": "Grounding delimitato completato",
                "duration_ms": 8,
            },
        },
    ]
    events = prefix_events + inserted + suffix_events
    for sequence, event in enumerate(events, start=1):
        event["data"]["sequence"] = sequence  # type: ignore[index]
    return events


def _observation(*, pair: int, arm: str) -> dict[str, object]:
    prefix = arm == "prefix"
    pair_order = ("direct", "prefix") if pair % 2 else ("prefix", "direct")
    return observation_from_terminal(
        pair=pair,
        arm=arm,
        request_sha256=_sha("request"),
        runtime_identity=_runtime_identity(),
        tenant_before=_tenant_guard(),
        tenant_after=_tenant_guard(),
        terminal=_terminal(prefix=prefix),
        events=_events(pair=pair, prefix=prefix),
        turn_ms=160 if prefix else 240,
        shape_contract=SHAPE_CONTRACT,
        ordinal=(pair - 1) * 2 + pair_order.index(arm) + 1,
    )


def _receipt(*, pairs: int = 6) -> dict[str, object]:
    observations = [
        observation
        for pair in range(1, pairs + 1)
        for observation in (
            _observation(pair=pair, arm="direct"),
            _observation(pair=pair, arm="prefix"),
        )
    ]
    return seal_latency_receipt(identity=_identity(), observations=observations)


def test_valid_paired_receipt_is_promoted_and_replays() -> None:
    receipt = _receipt()

    assert receipt["status"] == "PROMOTED"
    assert receipt["claims"]["decode_preflights_excluded_from_denominator"] == 2
    assert receipt["claims"]["shape_contract_oracle"] is True
    assert receipt["claims"]["compiled_endpoint_parity"] is True
    assert receipt["denominator"] == {
        "pairs": 6,
        "observations": 12,
        "in": 12,
        "out": 12,
        "distinct": 12,
        "gaps": 0,
    }
    assert verify_latency_receipt(receipt) == receipt


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda receipt: receipt["identity"].__setitem__("tenant_tree", "drift"),
            "authority identity",
        ),
        (
            lambda receipt: receipt["observations"][0].__setitem__("source_sha256", _sha("other")),
            "semantic output",
        ),
        (
            lambda receipt: receipt["observations"][1].__setitem__(
                "grounding_selections_sha256", _sha("other")
            ),
            "authority identity",
        ),
        (
            lambda receipt: receipt["observations"][0].__setitem__(
                "shape_contract_sha256", _sha("other")
            ),
            "authority identity",
        ),
        (
            lambda receipt: receipt["identity"].__setitem__(
                "decode_preflight_sha256", _sha("other")
            ),
            "decode preflight evidence",
        ),
        (
            lambda receipt: receipt["identity"]["decode_preflights"][0].__setitem__(
                "arm", "prefix"
            ),
            "decode preflight evidence",
        ),
    ],
)
def test_receipt_replay_rejects_identity_or_semantic_drift(mutator, message: str) -> None:
    receipt = _receipt()
    mutator(receipt)

    with pytest.raises(BrainError, match=message):
        verify_latency_receipt(receipt)


def test_observation_rejects_invalid_phase_and_cache_metrics() -> None:
    terminal = _terminal(prefix=False)
    metrics = terminal["identity"]["generation_metrics"]
    assert isinstance(metrics, dict)
    metrics["uncached_prompt_tokens"] = 1
    with pytest.raises(BrainError, match="phase telemetry"):
        observation_from_terminal(
            pair=1,
            arm="direct",
            request_sha256=_sha("request"),
            runtime_identity=_runtime_identity(),
            tenant_before=_tenant_guard(),
            tenant_after=_tenant_guard(),
            terminal=terminal,
            events=_events(pair=1),
            turn_ms=220,
            shape_contract=SHAPE_CONTRACT,
        )

    with pytest.raises(BrainError, match="cache arm"):
        observation_from_terminal(
            pair=1,
            arm="prefix",
            request_sha256=_sha("request"),
            runtime_identity=_runtime_identity(),
            tenant_before=_tenant_guard(),
            tenant_after=_tenant_guard(),
            terminal=_terminal(prefix=False),
            events=_events(pair=1),
            turn_ms=220,
            shape_contract=SHAPE_CONTRACT,
        )


def test_observation_reruns_product_grounding_oracle_before_redaction() -> None:
    wrong = _terminal(
        prefix=False,
        source="""metis 0.43
endpoint demo.test {
  take 24 from @play-demo.video {
    include where { @mood is "Drammatico" }
    return response.expanded
  }
}
""",
    )
    with pytest.raises(BrainError, match="grounding oracle"):
        observation_from_terminal(
            pair=1,
            arm="direct",
            request_sha256=_sha("request"),
            runtime_identity=_runtime_identity(),
            tenant_before=_tenant_guard(),
            tenant_after=_tenant_guard(),
            terminal=wrong,
            events=_events(pair=1),
            turn_ms=240,
            shape_contract=SHAPE_CONTRACT,
        )


def test_observation_rejects_wrong_shape_surface() -> None:
    wrong = _terminal(
        prefix=False,
        source="""metis 0.43
endpoint demo.a_b_test {
  take 24 from @play-demo.video {
    include where { @mood is "Romantico" }
    order by @publication_date ascending
    return response.expanded
  }
}
""",
    )
    with pytest.raises(BrainError, match="shape oracle"):
        observation_from_terminal(
            pair=1,
            arm="direct",
            request_sha256=_sha("request"),
            runtime_identity=_runtime_identity(),
            tenant_before=_tenant_guard(),
            tenant_after=_tenant_guard(),
            terminal=wrong,
            events=_events(pair=1),
            turn_ms=240,
            shape_contract=SHAPE_CONTRACT,
        )


def test_observation_rejects_self_consistent_wrong_take_against_frozen_shape() -> None:
    wrong = _terminal(
        prefix=False,
        source="""metis 0.43
endpoint demo.a_b_test {
  take 12 from @play-demo.video {
    include where { @mood is "Romantico" }
    order by @publication_date descending
    return response.expanded
  }
}
""",
    )
    wrong["grounding"]["output_contract"]["take"]["value"] = 12  # type: ignore[index]
    with pytest.raises(BrainError, match="shape oracle"):
        observation_from_terminal(
            pair=1,
            arm="direct",
            request_sha256=_sha("request"),
            runtime_identity=_runtime_identity(),
            tenant_before=_tenant_guard(),
            tenant_after=_tenant_guard(),
            terminal=wrong,
            events=_events(pair=1),
            turn_ms=240,
            shape_contract=SHAPE_CONTRACT,
        )


def test_observation_accepts_only_the_exact_flash_retry_route() -> None:
    observation = observation_from_terminal(
        pair=1,
        arm="direct",
        request_sha256=_sha("request"),
        runtime_identity=_runtime_identity(),
        tenant_before=_tenant_guard(),
        tenant_after=_tenant_guard(),
        terminal=_terminal(prefix=False, flash_retry=True),
        events=_flash_retry_events(prefix=False),
        turn_ms=280,
        shape_contract=SHAPE_CONTRACT,
    )

    assert observation["processing_route"] == "flash_retry"
    assert observation["retrieval_ms"] == 20
    assert observation["intent_ms"] == 7


def test_observation_rejects_event_sequence_gap() -> None:
    events = _events(pair=1)
    events[-1]["data"]["sequence"] = 5  # type: ignore[index]

    with pytest.raises(BrainError, match="sequence has a gap"):
        observation_from_terminal(
            pair=1,
            arm="direct",
            request_sha256=_sha("request"),
            runtime_identity=_runtime_identity(),
            tenant_before=_tenant_guard(),
            tenant_after=_tenant_guard(),
            terminal=_terminal(prefix=False),
            events=events,
            turn_ms=220,
            shape_contract=SHAPE_CONTRACT,
        )


def test_observation_rejects_swapped_canonical_phase_order() -> None:
    events = _events(pair=1)
    events[1], events[2] = events[2], events[1]
    events[1]["data"]["sequence"] = 2  # type: ignore[index]
    events[2]["data"]["sequence"] = 3  # type: ignore[index]

    with pytest.raises(BrainError, match="event order"):
        observation_from_terminal(
            pair=1,
            arm="direct",
            request_sha256=_sha("request"),
            runtime_identity=_runtime_identity(),
            tenant_before=_tenant_guard(),
            tenant_after=_tenant_guard(),
            terminal=_terminal(prefix=False),
            events=events,
            turn_ms=240,
            shape_contract=SHAPE_CONTRACT,
        )


def test_observation_rejects_missing_duration_or_mixed_turn_events() -> None:
    missing_duration = _events(pair=1)
    missing_duration[6]["data"].pop("duration_ms")  # type: ignore[union-attr]
    with pytest.raises(BrainError, match="phase duration"):
        observation_from_terminal(
            pair=1,
            arm="direct",
            request_sha256=_sha("request"),
            runtime_identity=_runtime_identity(),
            tenant_before=_tenant_guard(),
            tenant_after=_tenant_guard(),
            terminal=_terminal(prefix=False),
            events=missing_duration,
            turn_ms=240,
            shape_contract=SHAPE_CONTRACT,
        )

    mixed_turn = _events(pair=1)
    mixed_turn[5]["data"]["turn_id"] = "turn-other"  # type: ignore[index]
    with pytest.raises(BrainError, match="event payload"):
        observation_from_terminal(
            pair=1,
            arm="direct",
            request_sha256=_sha("request"),
            runtime_identity=_runtime_identity(),
            tenant_before=_tenant_guard(),
            tenant_after=_tenant_guard(),
            terminal=_terminal(prefix=False),
            events=mixed_turn,
            turn_ms=240,
            shape_contract=SHAPE_CONTRACT,
        )


def test_observation_rejects_external_tenant_guard_drift() -> None:
    after = _tenant_guard()
    after["target_sha256"] = _sha("modified-target")
    with pytest.raises(BrainError, match="tenant guard changed"):
        observation_from_terminal(
            pair=1,
            arm="direct",
            request_sha256=_sha("request"),
            runtime_identity=_runtime_identity(),
            tenant_before=_tenant_guard(),
            tenant_after=after,
            terminal=_terminal(prefix=False),
            events=_events(pair=1),
            turn_ms=240,
            shape_contract=SHAPE_CONTRACT,
        )


def test_seal_rejects_unredacted_or_incomplete_observation_rosters() -> None:
    observations = [
        observation
        for pair in range(1, 7)
        for observation in (
            _observation(pair=pair, arm="direct"),
            _observation(pair=pair, arm="prefix"),
        )
    ]
    observations[0]["raw_prompt"] = "SECRET"
    with pytest.raises(BrainError, match="observation roster"):
        seal_latency_receipt(identity=_identity(), observations=observations)

    incomplete = _events(pair=1)[:-1]
    with pytest.raises(BrainError, match="event roster is incomplete"):
        observation_from_terminal(
            pair=1,
            arm="direct",
            request_sha256=_sha("request"),
            runtime_identity=_runtime_identity(),
            tenant_before=_tenant_guard(),
            tenant_after=_tenant_guard(),
            terminal=_terminal(prefix=False),
            events=incomplete,
            turn_ms=220,
            shape_contract=SHAPE_CONTRACT,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("turn_ms", -999),
        ("retrieval_ms", "evil"),
        ("compile_ms", -5),
        ("host_inference_overhead_ms", -500),
        ("event_count", -1),
        ("heartbeat_count", 9_999_999),
        ("compiler_receipt_sha256", "SECRET"),
    ],
)
def test_seal_revalidates_every_redacted_observation_field(field: str, value: object) -> None:
    observations = [
        observation
        for pair in range(1, 7)
        for observation in (
            _observation(pair=pair, arm="direct"),
            _observation(pair=pair, arm="prefix"),
        )
    ]
    observations[0][field] = value
    with pytest.raises(BrainError):
        seal_latency_receipt(identity=_identity(), observations=observations)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), 1),
        (("route",), "remote"),
        (("identity", "generation_strategy"), "grounded_renderer"),
        (("validation", "attempts"), 2),
    ],
)
def test_observation_rejects_nonlocal_or_repaired_terminal(path, value: object) -> None:
    terminal = _terminal(prefix=False)
    target = terminal
    for key in path[:-1]:
        target = target[key]  # type: ignore[index,assignment]
    target[path[-1]] = value  # type: ignore[index]
    with pytest.raises(BrainError, match="benchmark|runtime identity"):
        observation_from_terminal(
            pair=1,
            arm="direct",
            request_sha256=_sha("request"),
            runtime_identity=_runtime_identity(),
            tenant_before=_tenant_guard(),
            tenant_after=_tenant_guard(),
            terminal=terminal,
            events=_events(pair=1),
            turn_ms=240,
            shape_contract=SHAPE_CONTRACT,
        )


def test_seal_binds_every_observation_to_frozen_runtime_identity() -> None:
    observations = [
        observation
        for pair in range(1, 7)
        for observation in (
            _observation(pair=pair, arm="direct"),
            _observation(pair=pair, arm="prefix"),
        )
    ]
    observations[0]["worker_sha256"] = _sha("other-worker")
    with pytest.raises(BrainError, match="authority identity drifted"):
        seal_latency_receipt(identity=_identity(), observations=observations)


def test_write_is_create_only_and_receipt_is_replayable(tmp_path: Path) -> None:
    receipt = _receipt()
    target = tmp_path / "receipt.json"
    write_latency_receipt(target, receipt)
    assert verify_latency_receipt(__import__("json").loads(target.read_text())) == receipt

    with pytest.raises(BrainError, match="publication failed"):
        write_latency_receipt(target, receipt)
    assert list(tmp_path.glob(".receipt.json.*.pending")) == []


def test_held_receipt_is_not_published_until_commit(tmp_path: Path) -> None:
    receipt = _receipt()
    target = tmp_path / "receipt.json"

    handle = write_latency_receipt(target, receipt, hold_parent=True)

    assert handle is not None
    assert not target.exists()
    assert len(list(tmp_path.glob(".receipt.json.*.pending"))) == 1

    handle.commit()

    assert verify_latency_receipt(__import__("json").loads(target.read_text())) == receipt
    assert list(tmp_path.glob(".receipt.json.*.pending")) == []


def test_held_receipt_discard_never_publishes_final_name(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    handle = write_latency_receipt(target, {"status": "sealed"}, hold_parent=True)

    assert handle is not None
    assert not target.exists()
    handle.discard()

    assert not target.exists()
    assert list(tmp_path.glob(".receipt.json.*.pending")) == []


def test_commit_fails_closed_if_final_name_appears(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    handle = write_latency_receipt(target, {"status": "sealed"}, hold_parent=True)
    assert handle is not None
    target.write_text("occupied\n", encoding="utf-8")

    with pytest.raises(BrainError, match="publication failed"):
        handle.commit()

    assert target.read_text(encoding="utf-8") == "occupied\n"
    assert list(tmp_path.glob(".receipt.json.*.pending")) == []


def test_confined_write_rejects_a_parent_swapped_to_symlink(tmp_path: Path) -> None:
    root = tmp_path / "authority"
    parent = root / "day"
    outside = tmp_path / "outside"
    parent.mkdir(parents=True)
    outside.mkdir()
    parent.rmdir()
    parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(BrainError, match="output parent"):
        write_latency_receipt(
            parent / "receipt.json",
            {"status": "sealed"},
            authority_root=root,
        )
    assert not (outside / "receipt.json").exists()


def test_held_parent_descriptor_discards_the_exact_file_after_path_swap(tmp_path: Path) -> None:
    root = tmp_path / "authority"
    parent = root / "day"
    moved = root / "moved"
    outside = tmp_path / "outside"
    parent.mkdir(parents=True)
    outside.mkdir()
    handle = write_latency_receipt(
        parent / "receipt.json",
        {"status": "sealed"},
        authority_root=root,
        hold_parent=True,
    )
    assert handle is not None
    parent.rename(moved)
    parent.symlink_to(outside, target_is_directory=True)

    handle.discard()

    assert not (moved / "receipt.json").exists()
    assert list(moved.glob(".receipt.json.*.pending")) == []
    assert not (outside / "receipt.json").exists()


def test_receipt_hash_is_stable_for_same_observations() -> None:
    first = _receipt()
    second = _receipt()
    assert first["receipt_sha256"] == second["receipt_sha256"]
    assert hashlib.sha256(str(first["receipt_sha256"]).encode()).hexdigest()
