from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from metis_model1 import brain_mlx_runtime as mlx_runtime
from metis_model1 import initial_local_qlora_runtime as qualified_runtime
from metis_model1.brain_mlx_runtime import MlxBrainModelRuntime, serialize_model_messages
from metis_model1.brain_model_runtime import ModelCandidate, ModelRequest
from metis_model1.brain_protocol import BrainError


def _request(
    instruction: str = "crea un endpoint",
    *,
    cancellation: threading.Event | None = None,
    take: dict[str, object] | None = None,
) -> ModelRequest:
    grounding: dict[str, object] = {
        "catalogs": ["play-demo.video"],
        "resolutions": [{"field": "genere", "value": "Azione"}],
        "selections": [{"field": "genere"}],
    }
    if take is not None:
        grounding["output_contract"] = {"take": take}
    return ModelRequest(
        instruction=instruction,
        intent="create",
        target_path="candidate.metis",
        endpoint="demo.endpoint",
        context={
            "language_version": "0.43",
            "semantic_schema": 2,
            "catalog": {"name": "play-demo.video"},
            "fields": [
                {"name": "genere", "type": "keyword"},
                {"name": "campo_non_selezionato", "type": "keyword"},
            ],
            "endpoint_templates": [{"path": "private-template.metis", "source": "TEMPLATE_MARKER"}],
        },
        grounding=grounding,
        previous_source=None,
        diagnostics=(),
        cancellation=cancellation,
    )


def _wait_for_process(runtime: MlxBrainModelRuntime) -> subprocess.Popen[bytes]:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        process = runtime._process  # noqa: SLF001 - process lifecycle invariant under test
        if process is not None:
            return process
        time.sleep(0.005)
    pytest.fail("worker process did not start")


def _assert_process_group_gone(pid: int) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)
    pytest.fail(f"worker process group {pid} survived termination")


@pytest.fixture
def runtime_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model = tmp_path / "model"
    adapter = tmp_path / "adapter"
    model.mkdir()
    adapter.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    (adapter / "adapters.safetensors").write_bytes(b"adapter")
    worker = tmp_path / "worker.py"

    monkeypatch.setattr(qualified_runtime, "_no_symlinks", lambda _path: None)
    monkeypatch.setattr(
        qualified_runtime,
        "_check_runtime",
        lambda: {"python": "3.12.10", "packages": {"mlx": "0.32.1"}},
    )
    monkeypatch.setattr(
        qualified_runtime,
        "_check_checkpoint",
        lambda path: {"revision": "model-revision", "path": str(path)},
    )
    monkeypatch.setattr(
        qualified_runtime,
        "verify_checkpoint",
        lambda path: {"model_revision": "model-revision", "global_step": 50, "path": str(path)},
    )
    monkeypatch.setattr(
        qualified_runtime,
        "_prefixed_sha256",
        lambda _path: "sha256:" + "a" * 64,
    )

    def make_worker(mode: str = "echo") -> tuple[Path, Path]:
        worker.write_text(
            "import json, signal, sys, time\n"
            f"MODE = {mode!r}\n"
            "if MODE == 'ignore_term': signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "if MODE == 'startup_delay': time.sleep(0.2)\n"
            "for line in sys.stdin:\n"
            "    request = json.loads(line)\n"
            "    if MODE == 'delay': time.sleep(0.2)\n"
            "    if request.get('operation') == 'warmup':\n"
            "        if MODE == 'warmup_malformed': print('not-json', flush=True); continue\n"
            "        print(json.dumps({\n"
            "            'schema_version': 2 if MODE == 'warmup_bad_schema' else 1,\n"
            "            'request_id': 'wrong' if MODE == 'warmup_mismatch' "
            "else request['request_id'],\n"
            "            'status': 'ready',\n"
            "            'worker_load_ms': -1 if MODE == 'warmup_bad_metrics' else 10,\n"
            "            'model_revision': 'wrong' if MODE == 'warmup_bad_identity' "
            "else 'model-revision',\n"
            "            'adapter_sha256': 'sha256:' + 'a' * 64,\n"
            "        }), flush=True)\n"
            "        continue\n"
            "    if MODE == 'ignore_term': time.sleep(60)\n"
            "    if MODE == 'selective_stall' "
            "and request['messages'][-1]['content'].startswith('attendi'):\n"
            "        time.sleep(60)\n"
            "    if MODE == 'death': sys.exit(0)\n"
            "    if MODE == 'partial':\n"
            "        sys.stdout.write('{'); sys.stdout.flush(); time.sleep(0.2); continue\n"
            "    if MODE == 'malformed': print('not-json', flush=True); continue\n"
            "    if MODE == 'mismatch': request['request_id'] = 'wrong'\n"
            "    if MODE == 'oversized': request['text'] = 'x' * 1000001\n"
            "    else: request['text'] = request['request_id']\n"
            "    print(json.dumps({\n"
            "        'request_id': request['request_id'],\n"
            "        'text': request['text'],\n"
            "        'peak_metal_gb': 1.0,\n"
            "        'worker_load_ms': 10,\n"
            "        'generation_ms': 20,\n"
            "        'prompt_tokens': 30,\n"
            "        'generation_tokens': 513 if MODE == 'bad_metrics' else 4,\n"
            "        'cached_tokens': 0,\n"
            "        'prompt_tps': 100.0,\n"
            "        'generation_tps': 2.0,\n"
            "        'finish_reason': 'unknown' if MODE == 'bad_finish' else 'stop',\n"
            "    }), flush=True)\n",
            encoding="utf-8",
        )
        return model, adapter

    def build(
        mode: str = "echo",
        *,
        timeout_seconds: float = 1.0,
        prefix_cache_enabled: bool = True,
    ) -> MlxBrainModelRuntime:
        make_worker(mode)
        return MlxBrainModelRuntime(
            python_path=sys.executable,
            model_path=model,
            adapter_path=adapter,
            worker_script=worker,
            timeout_seconds=timeout_seconds,
            prefix_cache_enabled=prefix_cache_enabled,
        )

    return build


def test_prompt_serialization_is_deterministic_and_complete() -> None:
    request = _request()
    assert serialize_model_messages(request) == serialize_model_messages(request)
    messages = serialize_model_messages(request)
    assert [item["role"] for item in messages] == ["system", "user", "user"]
    assert messages[0]["content"].startswith("You produce only valid Metis source.")
    assert "smallest compiler-valid change" in messages[0]["content"]
    assert (
        "never add an unrequested filter, ordering, ranking, or business rule"
        in messages[0]["content"]
    )
    assert (
        "grounding.selections is the complete final finite-predicate set" in messages[0]["content"]
    )
    assert "not a delta" in messages[0]["content"]
    assert "including variable-valued or boolean predicates" in messages[0]["content"]
    assert "time.fractional_second" in messages[0]["content"]
    assert "two or more assignments require a braced attributes group" in messages[0]["content"]
    assert "endpoint declaration name is exactly `demo.endpoint`" in messages[2]["content"]
    assert "catalog source is exactly `@play-demo.video`" in messages[2]["content"]
    assert "Finite filters belong under `include where`" in messages[2]["content"]
    assert "TENANT_CONTEXT_JSON" in messages[2]["content"]
    assert "crea un endpoint" in messages[2]["content"]
    assert '"grounding"' in messages[2]["content"]
    assert '"name":"genere"' in messages[2]["content"]
    assert "campo_non_selezionato" not in messages[2]["content"]
    assert "TEMPLATE_MARKER" not in messages[2]["content"]
    assert "F-4 exact JSON contract" not in messages[0]["content"]
    assert len(messages[0]["content"].encode("utf-8")) < 16 * 1024


def test_prompt_projection_keeps_fields_referenced_by_previous_source() -> None:
    request = replace(
        _request(),
        previous_source="metis 0.43\nendpoint demo.e { take 1 from @video include where "
        '@campo_non_selezionato is "x" }\n',
    )

    prompt = serialize_model_messages(request)[2]["content"]

    assert '"name":"genere"' in prompt
    assert '"name":"campo_non_selezionato"' in prompt
    assert "TEMPLATE_MARKER" not in prompt


@pytest.mark.parametrize(
    ("take", "expected", "forbidden"),
    [
        (
            {"mode": "count", "value": 24, "source": "operator_confirmed"},
            "exactly 24 total results with `take 24`",
            "pagination contract",
        ),
        (
            {"mode": "page", "page_size": {"mode": "tenant"}},
            "use the bare `take page`",
            "`take page default",
        ),
        (
            {
                "mode": "page",
                "page_size": {
                    "mode": "local_default",
                    "value": 24,
                    "source": "operator_confirmed",
                },
            },
            "use exactly `take page default 24`",
            "total results",
        ),
    ],
)
def test_prompt_serialization_states_take_contract(
    take: dict[str, object], expected: str, forbidden: str
) -> None:
    prompt = "\n".join(item["content"] for item in serialize_model_messages(_request(take=take)))
    assert expected in prompt
    assert forbidden not in prompt


def test_worker_is_started_once_and_closed_idempotently(runtime_factory) -> None:
    runtime = runtime_factory()
    first = runtime.generate(_request())
    second = runtime.generate(_request("modifica l'endpoint"))
    assert first.model_revision == "model-revision"
    assert first.adapter_sha256 == "sha256:" + "a" * 64
    assert first.metrics == {
        "worker_load_ms": 10,
        "generation_ms": 20,
        "prompt_tokens": 30,
        "generation_tokens": 4,
        "cached_tokens": 0,
        "cache_hit": False,
        "prompt_tps": 100.0,
        "generation_tps": 2.0,
        "finish_reason": "stop",
        "peak_metal_gb": 1.0,
    }
    assert first.source != second.source
    assert runtime.model_loaded
    runtime.close()
    runtime.close()
    assert not runtime.model_loaded
    with pytest.raises(BrainError) as raised:
        runtime.generate(_request())
    assert raised.value.code == "MODEL_RUNTIME_CLOSED"


def test_warmup_loads_without_generation_and_reuses_the_worker(runtime_factory) -> None:
    runtime = runtime_factory()
    warmup = runtime.warmup()
    assert warmup["status"] == "ready"
    assert type(warmup["duration_ms"]) is int
    assert 0 <= warmup["duration_ms"] <= 1000
    assert warmup["worker_load_ms"] == 10
    assert runtime.model_loaded
    assert runtime.warmup_status == "ready"
    assert runtime.warmup_duration_ms == warmup["duration_ms"]
    assert runtime.warmup_worker_load_ms == 10
    assert runtime.warmup_prefix_tokens == 0
    assert runtime.prefix_cache_ready is False
    assert runtime._process_requests == 0  # noqa: SLF001 - warmup is not inference
    assert runtime._process is not None  # noqa: SLF001 - lifecycle invariant under test
    pid = runtime._process.pid  # noqa: SLF001

    candidate = runtime.generate(_request("richiesta complessa"))

    assert candidate.source
    assert runtime._process_requests == 1  # noqa: SLF001
    assert runtime._process is not None  # noqa: SLF001
    assert runtime._process.pid == pid  # noqa: SLF001
    runtime.close()


def test_warmup_timeout_is_fail_closed(runtime_factory) -> None:
    runtime = runtime_factory("startup_delay", timeout_seconds=0.03)
    with pytest.raises(BrainError) as raised:
        runtime.warmup()
    assert raised.value.code == "MODEL_RUNTIME_TIMEOUT"
    assert runtime.warmup_status == "failed"
    assert not runtime.model_loaded
    with pytest.raises(BrainError) as second:
        runtime.generate(_request())
    assert second.value.code == "MODEL_RUNTIME_BROKEN"
    runtime.close()


@pytest.mark.parametrize(
    "mode",
    [
        "warmup_malformed",
        "warmup_bad_schema",
        "warmup_mismatch",
        "warmup_bad_metrics",
        "warmup_bad_identity",
    ],
)
def test_invalid_warmup_response_is_fail_closed(runtime_factory, mode: str) -> None:
    runtime = runtime_factory(mode)
    with pytest.raises(BrainError) as raised:
        runtime.warmup()
    assert raised.value.code == "MODEL_RESPONSE_INVALID"
    assert runtime.warmup_status == "failed"
    assert not runtime.model_loaded
    runtime.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"generation_tokens": 0},
        {"generation_tokens": 513},
        {"prompt_tokens": 1.5},
        {"cached_tokens": 31},
        {"finish_reason": "unknown"},
        {"peak_metal_gb": 111.0},
    ],
)
def test_model_candidate_rejects_invalid_injected_telemetry(changes: dict[str, object]) -> None:
    metrics: dict[str, int | float | str] = {
        "worker_load_ms": 10,
        "generation_ms": 20,
        "prompt_tokens": 30,
        "generation_tokens": 4,
        "cached_tokens": 0,
        "cache_hit": False,
        "prompt_tps": 100.0,
        "generation_tps": 2.0,
        "finish_reason": "stop",
        "peak_metal_gb": 1.0,
    }
    metrics.update(changes)
    with pytest.raises(BrainError) as raised:
        ModelCandidate("metis 0.43\n", metrics=metrics)
    assert raised.value.code == "MODEL_INVALID"


def test_prefix_is_stable_and_dynamic_request_data_is_after_it() -> None:
    first = serialize_model_messages(_request("prima richiesta"))
    second = serialize_model_messages(_request("seconda richiesta"))
    assert first[:2] == second[:2]
    assert first[2] != second[2]
    assert "prima richiesta" not in first[0]["content"]
    assert '"grounding"' not in first[0]["content"]


def test_qualification_cache_arm_can_only_toggle_one_warm_public_template() -> None:
    class Process:
        @staticmethod
        def poll() -> None:
            return None

    runtime = object.__new__(MlxBrainModelRuntime)
    runtime._request_lock = threading.Lock()  # noqa: SLF001 - qualification seam fixture
    runtime._closed = False  # noqa: SLF001
    runtime._broken = False  # noqa: SLF001
    runtime._process = Process()  # noqa: SLF001
    runtime._warmup_status = "ready"  # noqa: SLF001
    runtime._prefix_cache_enabled = True  # noqa: SLF001
    runtime._prefix_cache_ready = True  # noqa: SLF001
    runtime._warmup_prefix_tokens = 60  # noqa: SLF001
    runtime._cache_mode = "prefix"  # noqa: SLF001

    runtime._set_cache_mode_for_qualification("disabled")  # noqa: SLF001
    assert runtime.cache_mode == "disabled"
    runtime._set_cache_mode_for_qualification("prefix")  # noqa: SLF001
    assert runtime.cache_mode == "prefix"

    runtime._prefix_cache_ready = False  # noqa: SLF001
    with pytest.raises(BrainError, match="prefix template"):
        runtime._set_cache_mode_for_qualification("disabled")  # noqa: SLF001


def test_cache_scope_rejects_raw_or_unbounded_scope() -> None:
    with pytest.raises(BrainError, match="cache scope"):
        mlx_runtime._cache_scope("tenant/value")
    with pytest.raises(BrainError, match="cache scope"):
        mlx_runtime._cache_scope("x" * 129)


def test_legacy_wire_response_defaults_cache_hit_false(runtime_factory) -> None:
    runtime = runtime_factory()
    legacy = (
        b'{"request_id":"request","text":"metis 0.43\\n",'
        b'"peak_metal_gb":1.0,"worker_load_ms":10,"generation_ms":20,'
        b'"prompt_tokens":30,"generation_tokens":4,"cached_tokens":0,'
        b'"prompt_tps":100.0,"generation_tps":2.0,"finish_reason":"stop"}'
    )
    parsed = runtime._parse_response(legacy, "request")
    assert parsed["cache_hit"] is False
    runtime.close()


def test_cache_hit_telemetry_must_be_boolean(runtime_factory) -> None:
    runtime = runtime_factory()
    value = {
        "request_id": "request",
        "text": "metis 0.43\\n",
        "peak_metal_gb": 1.0,
        "worker_load_ms": 10,
        "generation_ms": 20,
        "prompt_tokens": 30,
        "generation_tokens": 4,
        "cached_tokens": 4,
        "cache_hit": 1,
        "prompt_tps": 100.0,
        "generation_tps": 2.0,
        "finish_reason": "stop",
    }
    with pytest.raises(BrainError, match="cache telemetry"):
        runtime._parse_response((__import__("json").dumps(value)).encode(), "request")
    runtime.close()


def test_cache_hit_telemetry_must_match_cached_tokens(runtime_factory) -> None:
    runtime = runtime_factory()
    value = {
        "request_id": "request",
        "text": "metis 0.43\n",
        "peak_metal_gb": 1.0,
        "worker_load_ms": 10,
        "generation_ms": 20,
        "prompt_tokens": 30,
        "generation_tokens": 4,
        "cached_tokens": 4,
        "cache_hit": False,
        "prompt_tps": 100.0,
        "generation_tps": 2.0,
        "finish_reason": "stop",
    }
    with pytest.raises(BrainError, match="cache telemetry"):
        runtime._parse_response((__import__("json").dumps(value)).encode(), "request")
    runtime.close()


def test_wire_three_phase_telemetry_is_strict_and_cache_mode_bound(runtime_factory) -> None:
    runtime = runtime_factory(prefix_cache_enabled=False)
    value = {
        "request_id": "request",
        "text": "metis 0.43\n",
        "peak_metal_gb": 1.0,
        "worker_load_ms": 10,
        "worker_request_ms": 131,
        "generation_ms": 120,
        "cache_prepare_ms": 2,
        "tokenization_ms": 4,
        "time_to_first_token_ms": 70,
        "decode_after_first_token_ms": 40,
        "generation_residual_ms": 10,
        "worker_residual_ms": 5,
        "prompt_tokens": 30,
        "uncached_prompt_tokens": 30,
        "generation_tokens": 4,
        "cached_tokens": 0,
        "cache_hit": False,
        "cache_mode": "disabled",
        "prompt_tps": 30_000.0 / 70.0,
        "generation_tps": 100.0,
        "finish_reason": "stop",
    }

    assert runtime._parse_response(json.dumps(value).encode(), "request") == value  # noqa: SLF001
    for key, replacement in (
        ("cache_mode", "prefix"),
        ("uncached_prompt_tokens", 29),
        ("cached_tokens", 1),
        ("generation_residual_ms", 20),
    ):
        invalid = {**value, key: replacement}
        if key == "cached_tokens":
            invalid["cache_hit"] = True
            invalid["uncached_prompt_tokens"] = 29
        with pytest.raises(BrainError, match="phase telemetry|disabled cache"):
            runtime._parse_response(json.dumps(invalid).encode(), "request")  # noqa: SLF001
    runtime.close()


def test_prompt_cache_clone_keeps_public_template_immutable() -> None:
    class FakeCache:
        def __init__(self) -> None:
            self.state = [[11, 22]]
            self.meta_state = ("prefix",)
            self.offset = 2

        def prefix_cache_snapshot(self) -> dict[str, object]:
            return {"state": self.state, "meta_state": self.meta_state}

        def prefix_cache_restore(self, snapshot: dict[str, object]) -> None:
            self.state = snapshot["state"]
            self.meta_state = snapshot["meta_state"]

    class FakeState:
        def __init__(self) -> None:
            self.token_ids: list[int] | None = None
            self.cache: list[FakeCache] | None = None

    template = FakeState()
    template.token_ids = [11, 22]
    template.cache = [FakeCache()]
    transient = qualified_runtime._clone_prompt_cache_state(
        template,
        make_cache=lambda: [FakeCache()],
        state_factory=FakeState,
    )

    assert transient is not None
    assert transient is not template
    assert transient.token_ids == [11, 22]
    assert transient.token_ids is not template.token_ids
    assert transient.cache is not template.cache
    assert transient.cache[0].state is not template.cache[0].state
    transient.token_ids.append(901)
    transient.cache[0].state.append([901])
    assert template.token_ids == [11, 22]
    assert template.cache[0].state == [[11, 22]]
    second_session = qualified_runtime._clone_prompt_cache_state(
        template,
        make_cache=lambda: [FakeCache()],
        state_factory=FakeState,
    )
    assert second_session is not None
    assert second_session.token_ids == [11, 22]
    assert second_session.cache[0].state == [[11, 22]]
    assert 901 not in second_session.token_ids
    assert [901] not in second_session.cache[0].state


def test_prompt_cache_clone_fails_closed_on_incompatible_cache_roster() -> None:
    class State:
        token_ids = [11, 22]
        cache = [object()]

    assert (
        qualified_runtime._clone_prompt_cache_state(
            State(), make_cache=lambda: [], state_factory=State
        )
        is None
    )


def test_prompt_cache_clone_fails_closed_on_wrong_logical_offset() -> None:
    class Cache:
        offset = 3
        state = [[11, 22, 33]]
        meta_state = ()

        def prefix_cache_snapshot(self) -> dict[str, object]:
            return {"state": self.state, "meta_state": self.meta_state}

        def prefix_cache_restore(self, snapshot: dict[str, object]) -> None:
            self.state = snapshot["state"]
            self.meta_state = snapshot["meta_state"]

    class State:
        token_ids = [11, 22]
        cache = [Cache()]

    assert (
        qualified_runtime._clone_prompt_cache_state(
            State(), make_cache=lambda: [Cache()], state_factory=State
        )
        is None
    )


def test_concurrent_calls_are_serialized(runtime_factory) -> None:
    runtime = runtime_factory("delay", timeout_seconds=2.0)
    values: list[str] = []
    errors: list[Exception] = []

    def call() -> None:
        try:
            values.append(runtime.generate(_request()).source)
        except Exception as error:  # pragma: no cover - assertion below reports it
            errors.append(error)

    threads = [threading.Thread(target=call) for _ in range(4)]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.monotonic() - started
    runtime.close()
    assert errors == []
    assert len(values) == 4
    assert len(set(values)) == 4
    assert elapsed >= 0.75


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("malformed", "MODEL_RESPONSE_INVALID"),
        ("mismatch", "MODEL_RESPONSE_INVALID"),
        ("oversized", "MODEL_RESPONSE_INVALID"),
        ("bad_metrics", "MODEL_RESPONSE_INVALID"),
        ("bad_finish", "MODEL_RESPONSE_INVALID"),
        ("death", "MODEL_RUNTIME_DIED"),
    ],
)
def test_bad_worker_responses_fail_closed(runtime_factory, mode: str, code: str) -> None:
    runtime = runtime_factory(mode)
    with pytest.raises(BrainError) as raised:
        runtime.generate(_request())
    assert raised.value.code == code
    assert not runtime.model_loaded
    with pytest.raises(BrainError) as second:
        runtime.generate(_request())
    assert second.value.code == "MODEL_RUNTIME_BROKEN"
    runtime.close()


def test_worker_timeout_terminates_and_breaks_runtime(runtime_factory) -> None:
    runtime = runtime_factory("delay", timeout_seconds=0.02)
    with pytest.raises(BrainError) as raised:
        runtime.generate(_request())
    assert raised.value.code == "MODEL_RUNTIME_TIMEOUT"
    assert not runtime.model_loaded
    runtime.close()


@pytest.mark.parametrize("mode", ["partial", "startup_delay"])
def test_worker_deadline_covers_partial_read_and_blocked_write(runtime_factory, mode: str) -> None:
    runtime = runtime_factory(mode, timeout_seconds=0.03)
    request = _request("x" * 500_000) if mode == "startup_delay" else _request()
    started = time.monotonic()
    with pytest.raises(BrainError) as raised:
        runtime.generate(request)
    elapsed = time.monotonic() - started
    assert raised.value.code == "MODEL_RUNTIME_TIMEOUT"
    assert elapsed < 0.15
    runtime.close()


def test_worker_is_recycled_before_qualified_request_cap(runtime_factory) -> None:
    runtime = runtime_factory(timeout_seconds=2.0)
    runtime.generate(_request())
    assert runtime._process is not None  # noqa: SLF001 - lifecycle invariant under test
    first_pid = runtime._process.pid  # noqa: SLF001
    for index in range(119):
        runtime.generate(_request(f"richiesta {index}"))
    assert runtime._process is not None  # noqa: SLF001
    assert runtime._process.pid == first_pid  # noqa: SLF001
    runtime.generate(_request("richiesta dopo il riciclo"))
    assert runtime._process is not None  # noqa: SLF001
    assert runtime._process.pid != first_pid  # noqa: SLF001
    runtime.close()


def test_already_cancelled_request_never_starts_worker(runtime_factory) -> None:
    runtime = runtime_factory()
    cancellation = threading.Event()
    cancellation.set()
    with pytest.raises(BrainError) as raised:
        runtime.generate(_request(cancellation=cancellation))
    assert raised.value.code == "MODEL_GENERATION_CANCELLED"
    assert runtime._process is None  # noqa: SLF001 - no cancelled cold start
    assert runtime.warmup_status == "cold"
    runtime.close()


def test_dead_warm_worker_clears_warmup_telemetry(runtime_factory) -> None:
    runtime = runtime_factory()
    runtime.warmup()
    process = _wait_for_process(runtime)
    process.kill()
    process.wait(timeout=2.0)

    with pytest.raises(BrainError) as raised:
        runtime.generate(_request())

    assert raised.value.code == "MODEL_RUNTIME_DIED"
    assert runtime.warmup_status == "failed"
    assert runtime.warmup_duration_ms is None
    assert runtime.warmup_worker_load_ms is None
    assert not runtime.model_loaded
    runtime.close()


def test_production_worker_is_reverified_at_lazy_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "model"
    adapter = tmp_path / "adapter"
    model.mkdir()
    adapter.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    (adapter / "adapters.safetensors").write_bytes(b"adapter")
    worker = Path(mlx_runtime.__file__).with_name("initial_local_qlora_runtime.py")
    worker_digest_reads = 0

    monkeypatch.setattr(qualified_runtime, "_no_symlinks", lambda _path: None)
    monkeypatch.setattr(
        qualified_runtime,
        "_check_runtime",
        lambda: {"python": "3.12.10", "packages": {"mlx": "0.32.1"}},
    )
    monkeypatch.setattr(
        qualified_runtime,
        "_check_checkpoint",
        lambda path: {"revision": "model-revision", "path": str(path)},
    )
    monkeypatch.setattr(
        qualified_runtime,
        "verify_checkpoint",
        lambda path: {"model_revision": "model-revision", "global_step": 50, "path": str(path)},
    )

    def digest(path: Path) -> str:
        nonlocal worker_digest_reads
        if Path(path) == worker:
            worker_digest_reads += 1
            if worker_digest_reads == 1:
                return mlx_runtime.WORKER_SHA256
            return "sha256:" + "0" * 64
        return "sha256:" + "a" * 64

    monkeypatch.setattr(qualified_runtime, "_prefixed_sha256", digest)
    runtime = MlxBrainModelRuntime(
        python_path=sys.executable,
        model_path=model,
        adapter_path=adapter,
        timeout_seconds=1.0,
    )
    with pytest.raises(BrainError) as raised:
        runtime.generate(_request())
    assert raised.value.code == "MODEL_RUNTIME_CONFIG"
    assert worker_digest_reads == 2
    assert runtime._process is None  # noqa: SLF001 - no unpinned process may start
    runtime.close()


def test_production_worker_pin_matches_the_tracked_worker() -> None:
    worker = Path(mlx_runtime.__file__).with_name("initial_local_qlora_runtime.py")
    assert qualified_runtime._prefixed_sha256(worker) == mlx_runtime.WORKER_SHA256


def test_cancel_stalled_generation_terminates_worker_and_runtime_recovers(runtime_factory) -> None:
    runtime = runtime_factory("selective_stall", timeout_seconds=30.0)
    cancellation = threading.Event()
    errors: list[Exception] = []

    def generate() -> None:
        try:
            runtime.generate(_request("attendi", cancellation=cancellation))
        except Exception as error:  # pragma: no cover - assertions below report it
            errors.append(error)

    thread = threading.Thread(target=generate)
    thread.start()
    process = _wait_for_process(runtime)
    cancellation.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], BrainError)
    assert errors[0].code == "MODEL_GENERATION_CANCELLED"
    _assert_process_group_gone(process.pid)
    assert not runtime.model_loaded

    recovered = runtime.generate(_request("riparti"))
    assert recovered.source
    assert runtime.model_loaded
    runtime.close()


def test_close_stalled_generation_is_bounded_and_leaves_no_orphan(
    runtime_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mlx_runtime, "TERMINATE_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(mlx_runtime, "KILL_WAIT_SECONDS", 1.0)
    runtime = runtime_factory("ignore_term", timeout_seconds=30.0)
    errors: list[Exception] = []

    def generate() -> None:
        try:
            runtime.generate(_request())
        except Exception as error:  # pragma: no cover - assertions below report it
            errors.append(error)

    thread = threading.Thread(target=generate)
    thread.start()
    process = _wait_for_process(runtime)
    time.sleep(0.2)
    started = time.monotonic()
    runtime.close()
    elapsed = time.monotonic() - started
    thread.join(timeout=2.0)

    assert elapsed < 1.5
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], BrainError)
    assert errors[0].code == "MODEL_RUNTIME_DIED"
    _assert_process_group_gone(process.pid)
    with pytest.raises(BrainError) as raised:
        runtime.generate(_request())
    assert raised.value.code == "MODEL_RUNTIME_CLOSED"


def test_oversized_request_is_rejected_before_worker_start(runtime_factory) -> None:
    runtime = runtime_factory()
    with pytest.raises(BrainError) as raised:
        runtime.generate(_request("x" * 1_000_000))
    assert raised.value.code == "MODEL_INPUT_TOO_LARGE"
    assert not runtime.model_loaded
    runtime.close()


@pytest.mark.parametrize(
    "field",
    ["python_path", "model_path", "adapter_path"],
)
def test_relative_paths_are_rejected(runtime_factory, field: str) -> None:
    runtime_factory()
    kwargs = {
        "python_path": sys.executable,
        "model_path": "/tmp/model",
        "adapter_path": "/tmp/adapter",
        "worker_script": Path(__file__),
    }
    kwargs[field] = "relative/path"
    with pytest.raises(BrainError) as raised:
        MlxBrainModelRuntime(**kwargs)
    assert raised.value.code == "MODEL_RUNTIME_CONFIG"


def test_model_symlink_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = tmp_path / "model"
    adapter = tmp_path / "adapter"
    model.mkdir()
    adapter.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    (adapter / "adapters.safetensors").write_bytes(b"adapter")
    link = tmp_path / "model-link"
    link.symlink_to(model, target_is_directory=True)
    with pytest.raises(BrainError) as raised:
        MlxBrainModelRuntime(
            python_path=sys.executable,
            model_path=link,
            adapter_path=adapter,
            worker_script=Path(__file__),
        )
    assert raised.value.code == "MODEL_RUNTIME_CONFIG"


def test_model_and_adapter_identity_must_match(runtime_factory, monkeypatch) -> None:
    runtime_factory()
    monkeypatch.setattr(
        qualified_runtime,
        "verify_checkpoint",
        lambda _path: {"model_revision": "other-revision", "global_step": 50},
    )
    with pytest.raises(BrainError) as raised:
        MlxBrainModelRuntime(
            python_path=sys.executable,
            model_path=Path.cwd(),
            adapter_path=Path.cwd(),
            worker_script=Path(__file__),
        )
    assert raised.value.code == "MODEL_RUNTIME_CONFIG"
