from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from metis_model1 import brain_mlx_runtime as mlx_runtime
from metis_model1 import initial_local_qlora_runtime as qualified_runtime
from metis_model1.brain_mlx_runtime import MlxBrainModelRuntime, serialize_model_messages
from metis_model1.brain_model_runtime import ModelRequest
from metis_model1.brain_protocol import BrainError


def _request(
    instruction: str = "crea un endpoint",
    *,
    cancellation: threading.Event | None = None,
    take: dict[str, object] | None = None,
) -> ModelRequest:
    grounding: dict[str, object] = {"resolutions": [{"field": "genere", "value": "Azione"}]}
    if take is not None:
        grounding["output_contract"] = {"take": take}
    return ModelRequest(
        instruction=instruction,
        intent="create",
        target_path="candidate.metis",
        endpoint="demo.endpoint",
        context={"catalog": "video", "fields": ["genere"]},
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
            "    }), flush=True)\n",
            encoding="utf-8",
        )
        return model, adapter

    def build(mode: str = "echo", *, timeout_seconds: float = 1.0) -> MlxBrainModelRuntime:
        make_worker(mode)
        return MlxBrainModelRuntime(
            python_path=sys.executable,
            model_path=model,
            adapter_path=adapter,
            worker_script=worker,
            timeout_seconds=timeout_seconds,
        )

    return build


def test_prompt_serialization_is_deterministic_and_complete() -> None:
    request = _request()
    assert serialize_model_messages(request) == serialize_model_messages(request)
    messages = serialize_model_messages(request)
    assert [item["role"] for item in messages] == ["system", "user"]
    assert messages[0]["content"].startswith("You produce only valid Metis source.")
    assert "smallest compiler-valid change" in messages[0]["content"]
    assert (
        "never add an unrequested filter, ordering, ranking, or business rule"
        in messages[0]["content"]
    )
    assert "time.fractional_second" in messages[0]["content"]
    assert "two or more assignments require a braced attributes group" in messages[0]["content"]
    assert "TENANT_CONTEXT_JSON" in messages[1]["content"]
    assert messages[1]["content"].startswith("crea un endpoint\n\n")
    assert '"grounding"' in messages[1]["content"]


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
    prompt = serialize_model_messages(_request(take=take))[0]["content"]
    assert expected in prompt
    assert forbidden not in prompt


def test_worker_is_started_once_and_closed_idempotently(runtime_factory) -> None:
    runtime = runtime_factory()
    first = runtime.generate(_request())
    second = runtime.generate(_request("modifica l'endpoint"))
    assert first.model_revision == "model-revision"
    assert first.adapter_sha256 == "sha256:" + "a" * 64
    assert first.source != second.source
    assert runtime.model_loaded
    runtime.close()
    runtime.close()
    assert not runtime.model_loaded
    with pytest.raises(BrainError) as raised:
        runtime.generate(_request())
    assert raised.value.code == "MODEL_RUNTIME_CLOSED"


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
