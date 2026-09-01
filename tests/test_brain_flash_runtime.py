from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from metis_model1 import brain_flash_runtime as flash_runtime
from metis_model1 import initial_local_qlora_runtime as qualified_runtime
from metis_model1.brain_intent_ir import (
    FLASH_INTENT_SCHEMA_SHA256,
    IntentCompileRequest,
)
from metis_model1.brain_protocol import BrainError, canonical_json

IDENTITY = {
    "status": "qualified",
    "model_revision": flash_runtime.EXPECTED_MODEL_REVISION,
    "schema_sha256": FLASH_INTENT_SCHEMA_SHA256,
    "decoder": flash_runtime.EXPECTED_DECODER,
}


def _request(
    instruction: str = "crea un endpoint per film italiani",
    *,
    cancellation: threading.Event | None = None,
) -> IntentCompileRequest:
    return IntentCompileRequest(
        instruction=instruction,
        intent="create",
        target_mode="create",
        cancellation=cancellation,
    )


def _valid_ir() -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": "create",
        "target_scope": "new",
        "concept_logic": "all",
        "concepts": [
            {
                "source": "film italiani",
                "query": "film prodotti in Italia",
                "polarity": "include",
            }
        ],
        "response_format": "unspecified",
        "fallback": "unspecified",
        "ambiguities": [],
    }


def _metrics() -> dict[str, object]:
    return {
        "worker_load_ms": 4,
        "generation_ms": 8,
        "prompt_tokens": 32,
        "generation_tokens": 24,
        "prompt_tps": 100.0,
        "generation_tps": 50.0,
        "finish_reason": "stop",
        "peak_metal_gb": 1.0,
    }


def _compile_response(request_id: str, *, mode: str = "ok") -> bytes:
    if mode == "duplicate":
        return (
            b'{"schema_version":1,"request_id":"'
            + request_id.encode()
            + b'","request_id":"duplicate"}\n'
        )
    if mode == "malformed":
        return b"not-json\n"
    if mode == "trailing":
        value = {
            "schema_version": 1,
            "request_id": request_id,
            "intent_ir": _valid_ir(),
            "model_revision": flash_runtime.EXPECTED_MODEL_REVISION,
            "schema_sha256": FLASH_INTENT_SCHEMA_SHA256,
            "decoder": flash_runtime.EXPECTED_DECODER,
            "metrics": _metrics(),
        }
        return canonical_json(value) + b"\n{}\n"
    if mode == "oversized":
        return b"{" + b"x" * (flash_runtime.MAX_WORKER_RESPONSE_BYTES + 1) + b"}\n"
    value: dict[str, object] = {
        "schema_version": 1,
        "request_id": request_id,
        "intent_ir": _valid_ir(),
        "model_revision": flash_runtime.EXPECTED_MODEL_REVISION,
        "schema_sha256": FLASH_INTENT_SCHEMA_SHA256,
        "decoder": flash_runtime.EXPECTED_DECODER,
        "metrics": _metrics(),
    }
    if mode == "bad_schema":
        value["schema_version"] = 2
    elif mode == "bad_request_id":
        value["request_id"] = "wrong"
    elif mode == "bad_model":
        value["model_revision"] = "other"
    elif mode == "bad_schema_identity":
        value["schema_sha256"] = "sha256:" + "0" * 64
    elif mode == "bad_decoder":
        value["decoder"] = "unconstrained"
    elif mode == "bad_ir":
        value["intent_ir"] = {
            **_valid_ir(),
            "concepts": [
                {
                    "source": "non presente",
                    "query": "film",
                    "polarity": "include",
                }
            ],
        }
    elif mode == "bad_extra":
        value["catalog"] = "video"
    elif mode == "bad_metrics":
        value["metrics"] = {**_metrics(), "generation_tokens": 0}
    elif mode == "bad_finish":
        value["metrics"] = {**_metrics(), "finish_reason": "length"}
    elif mode == "bad_nan":
        value["metrics"] = {**_metrics(), "generation_tps": float("nan")}
    return json.dumps(value, allow_nan=True, separators=(",", ":")).encode() + b"\n"


def _write_worker(path: Path, mode: str) -> None:
    # The wrapper passes the real Python executable through without requiring
    # sandbox-exec, keeping these tests fully local and deterministic.
    source = r"""
import json
import os
import signal
import sys
import time

MODE = __MODE__

def metrics():
    return {
        "worker_load_ms": 4,
        "generation_ms": 8,
        "prompt_tokens": 32,
        "generation_tokens": 24,
        "prompt_tps": 100.0,
        "generation_tps": 50.0,
        "finish_reason": "stop",
        "peak_metal_gb": 1.0,
    }

def ir():
    return {
        "schema_version": 1,
        "operation": "create",
        "target_scope": "new",
        "concept_logic": "all",
        "concepts": [{
            "source": "film italiani",
            "query": "film prodotti in Italia",
            "polarity": "include",
        }],
        "response_format": "unspecified",
        "fallback": "unspecified",
        "ambiguities": [],
    }

for line in sys.stdin:
    request = json.loads(line)
    request_id = request["request_id"]
    if request.get("operation") == "warmup":
        if MODE == "warmup_delay":
            time.sleep(60)
        if MODE == "warmup_malformed":
            print("not-json", flush=True)
            continue
        warmup = {
            "schema_version": 1,
            "request_id": request_id,
            "status": "ready",
            "worker_load_ms": 4,
            "model_revision": "475b9088d29754a3379866cf5aeb6b41acd313c2",
            "schema_sha256": (
                "sha256:972eb339d8f0f22f4d5dd43aa9f4f74ae49e2a6e2b3b7ff536a60444edd864fa"
            ),
            "decoder": "llguidance-1.8.0",
        }
        if MODE == "warmup_bad_schema":
            warmup["schema_version"] = 2
        elif MODE == "warmup_bad_request_id":
            warmup["request_id"] = "wrong"
        elif MODE == "warmup_bad_model":
            warmup["model_revision"] = "other"
        elif MODE == "warmup_bad_schema_identity":
            warmup["schema_sha256"] = "sha256:" + "0" * 64
        elif MODE == "warmup_bad_decoder":
            warmup["decoder"] = "unconstrained"
        elif MODE == "warmup_bad_metrics":
            warmup["worker_load_ms"] = -1
        elif MODE == "warmup_extra":
            warmup["extra"] = True
        print(json.dumps(warmup, separators=(",", ":")), flush=True)
        continue
    if MODE == "delay":
        time.sleep(60)
    if MODE == "stall" or MODE == "ignore_term":
        if MODE == "ignore_term":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(60)
    if MODE == "death":
        sys.exit(0)
    if MODE == "stderr_overflow":
        sys.stderr.write("x" * 140000)
        sys.stderr.flush()
    if MODE in ("malformed", "duplicate", "trailing", "oversized"):
        if MODE == "malformed":
            sys.stdout.write("not-json\n")
        elif MODE == "duplicate":
            sys.stdout.write(
                "{\"schema_version\":1,\"request_id\":\""
                + request_id
                + "\",\"request_id\":\"duplicate\"}\n"
            )
        elif MODE == "trailing":
            value = {
                "schema_version": 1,
                "request_id": request_id,
                "intent_ir": ir(),
                "model_revision": "475b9088d29754a3379866cf5aeb6b41acd313c2",
                "schema_sha256": (
                    "sha256:972eb339d8f0f22f4d5dd43aa9f4f74ae49e2a6e2b3b7ff536a60444edd864fa"
                ),
                "decoder": "llguidance-1.8.0",
                "metrics": metrics(),
            }
            sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n{}\n")
        else:
            sys.stdout.write("{" + "x" * 700000 + "}\n")
        sys.stdout.flush()
        continue
    value = {
        "schema_version": 1,
        "request_id": request_id,
        "intent_ir": ir(),
        "model_revision": "475b9088d29754a3379866cf5aeb6b41acd313c2",
        "schema_sha256": "sha256:972eb339d8f0f22f4d5dd43aa9f4f74ae49e2a6e2b3b7ff536a60444edd864fa",
        "decoder": "llguidance-1.8.0",
        "metrics": metrics(),
    }
    if MODE == "bad_schema": value["schema_version"] = 2
    elif MODE == "bad_request_id": value["request_id"] = "wrong"
    elif MODE == "bad_model": value["model_revision"] = "other"
    elif MODE == "bad_schema_identity": value["schema_sha256"] = "sha256:" + "0" * 64
    elif MODE == "bad_decoder": value["decoder"] = "unconstrained"
    elif MODE == "bad_ir": value["intent_ir"]["concepts"][0]["source"] = "non presente"
    elif MODE == "bad_extra": value["catalog"] = "video"
    elif MODE == "bad_metrics": value["metrics"]["generation_tokens"] = 0
    elif MODE == "bad_finish": value["metrics"]["finish_reason"] = "length"
    elif MODE == "bad_nan": value["metrics"]["generation_tps"] = float("nan")
    elif MODE == "stderr_overflow": pass
    sys.stdout.write(json.dumps(value, allow_nan=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()
""".replace("__MODE__", repr(mode))
    path.write_text(source, encoding="utf-8")


@pytest.fixture
def runtime_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model = tmp_path / "model"
    model.mkdir()
    (model / "marker").write_text("test", encoding="utf-8")
    worker = tmp_path / "worker.py"
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_bytes(flash_runtime.FLASH_INTENT_SCHEMA_PATH.read_bytes())
    sandbox = tmp_path / "sandbox-wrapper"
    sandbox.write_text(
        '#!/bin/sh\n[ "$1" = "-p" ] || exit 97\nshift 2\nexec "$@"\n',
        encoding="utf-8",
    )
    sandbox.chmod(stat.S_IRWXU)
    monkeypatch.setattr(qualified_runtime, "SANDBOX_EXEC", sandbox)
    monkeypatch.setattr(qualified_runtime, "EVALUATION_CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(flash_runtime, "_worker_environment", lambda: os.environ.copy())

    def build(
        mode: str = "ok", *, timeout_seconds: float = 1.0
    ) -> flash_runtime.MlxFlashIntentRuntime:
        _write_worker(worker, mode)
        return flash_runtime.MlxFlashIntentRuntime(
            python_path=sys.executable,
            model_path=model,
            timeout_seconds=timeout_seconds,
            worker_script=worker,
            manifest_path=manifest,
            schema_path=schema,
            qualified_identity=IDENTITY,
        )

    return build, {
        "model": model,
        "worker": worker,
        "manifest": manifest,
        "schema": schema,
        "sandbox": sandbox,
    }


def _wait_for_process(runtime: flash_runtime.MlxFlashIntentRuntime) -> subprocess.Popen[bytes]:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        process = runtime._process  # noqa: SLF001 - lifecycle invariant under test
        if process is not None:
            return process
        time.sleep(0.005)
    pytest.fail("Flash worker process did not start")


def _assert_process_group_gone(pid: int) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)
    pytest.fail(f"Flash worker process group {pid} survived termination")


def test_warmup_and_compile_reuse_one_worker(runtime_factory) -> None:
    build, _paths = runtime_factory
    runtime = build()
    warmup = runtime.warmup()
    process = _wait_for_process(runtime)
    assert warmup == {
        "status": "ready",
        "duration_ms": warmup["duration_ms"],
        "worker_load_ms": 4,
    }
    assert runtime.warmup_status == "ready"
    assert runtime.model_loaded
    assert runtime.warmup_worker_load_ms == 4
    assert runtime.warmup() == warmup
    candidate = runtime.compile(_request())
    assert candidate.intent_ir.exact_semantic_instruction == "film italiani"
    assert candidate.metrics["finish_reason"] == "stop"
    assert runtime._process is not None  # noqa: SLF001
    assert runtime._process.pid == process.pid  # noqa: SLF001
    runtime.close()
    runtime.close()
    assert not runtime.model_loaded


@pytest.mark.parametrize(
    "mode",
    [
        "warmup_malformed",
        "warmup_bad_schema",
        "warmup_bad_request_id",
        "warmup_bad_model",
        "warmup_bad_schema_identity",
        "warmup_bad_decoder",
        "warmup_bad_metrics",
        "warmup_extra",
    ],
)
def test_warmup_response_is_strict_and_fail_closed(runtime_factory, mode: str) -> None:
    build, _paths = runtime_factory
    runtime = build(mode)
    with pytest.raises(BrainError) as raised:
        runtime.warmup()
    assert raised.value.code == "FLASH_RESPONSE_INVALID"
    assert runtime.warmup_status == "failed"
    assert not runtime.model_loaded
    runtime.close()


@pytest.mark.parametrize(
    "mode",
    [
        "malformed",
        "duplicate",
        "trailing",
        "oversized",
        "bad_schema",
        "bad_request_id",
        "bad_model",
        "bad_schema_identity",
        "bad_decoder",
        "bad_ir",
        "bad_extra",
        "bad_metrics",
        "bad_finish",
        "bad_nan",
    ],
)
def test_compile_response_identity_ir_and_telemetry_are_strict(runtime_factory, mode: str) -> None:
    build, _paths = runtime_factory
    runtime = build(mode)
    with pytest.raises(BrainError) as raised:
        runtime.compile(_request())
    assert raised.value.code == "FLASH_RESPONSE_INVALID"
    assert not runtime.model_loaded
    with pytest.raises(BrainError) as second:
        runtime.compile(_request())
    assert second.value.code == "FLASH_RUNTIME_BROKEN"
    runtime.close()


def test_timeout_terminates_worker_and_breaks_runtime(runtime_factory) -> None:
    build, _paths = runtime_factory
    runtime = build("delay", timeout_seconds=0.03)
    with pytest.raises(BrainError) as raised:
        runtime.compile(_request())
    assert raised.value.code == "FLASH_RUNTIME_TIMEOUT"
    assert runtime.warmup_status == "failed"
    assert not runtime.model_loaded
    runtime.close()


def test_cancelled_compile_terminates_worker_and_allows_no_reuse(runtime_factory) -> None:
    build, _paths = runtime_factory
    runtime = build("stall", timeout_seconds=30.0)
    cancellation = threading.Event()
    errors: list[Exception] = []

    def call() -> None:
        try:
            runtime.compile(_request("attendi", cancellation=cancellation))
        except Exception as error:  # pragma: no cover - assertion below reports it
            errors.append(error)

    thread = threading.Thread(target=call)
    thread.start()
    process = _wait_for_process(runtime)
    time.sleep(0.05)
    cancellation.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], BrainError)
    assert errors[0].code == "FLASH_COMPILATION_CANCELLED"
    _assert_process_group_gone(process.pid)
    assert not runtime.model_loaded
    runtime.close()


def test_worker_death_is_fail_closed_and_no_orphan(runtime_factory) -> None:
    build, _paths = runtime_factory
    runtime = build("death")
    with pytest.raises(BrainError) as raised:
        runtime.compile(_request())
    assert raised.value.code == "FLASH_RUNTIME_DIED"
    assert runtime.warmup_status == "failed"
    assert not runtime.model_loaded
    runtime.close()


def test_worker_is_recycled_at_request_cap(
    runtime_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    build, _paths = runtime_factory
    monkeypatch.setattr(flash_runtime, "MAX_REQUESTS_PER_PROCESS", 2)
    runtime = build()
    runtime.compile(_request("uno film italiani"))
    first_pid = runtime._process.pid  # noqa: SLF001
    runtime.compile(_request("due film italiani"))
    assert runtime._process.pid == first_pid  # noqa: SLF001
    runtime.compile(_request("tre film italiani"))
    assert runtime._process.pid != first_pid  # noqa: SLF001
    runtime.close()


def test_already_cancelled_request_never_starts_worker(runtime_factory) -> None:
    build, _paths = runtime_factory
    runtime = build()
    cancellation = threading.Event()
    cancellation.set()
    with pytest.raises(BrainError) as raised:
        runtime.compile(_request(cancellation=cancellation))
    assert raised.value.code == "FLASH_COMPILATION_CANCELLED"
    assert runtime._process is None  # noqa: SLF001
    assert runtime.warmup_status == "cold"
    runtime.close()


def test_oversized_input_is_rejected_before_worker_start(
    runtime_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    build, _paths = runtime_factory
    runtime = build()
    monkeypatch.setattr(flash_runtime, "MAX_WORKER_REQUEST_BYTES", 16)
    with pytest.raises(BrainError) as raised:
        runtime.compile(_request())
    assert raised.value.code == "FLASH_INPUT_TOO_LARGE"
    assert runtime._process is None  # noqa: SLF001
    runtime.close()


@pytest.mark.parametrize(
    "field", ["python_path", "model_path", "worker_script", "manifest_path", "schema_path"]
)
def test_relative_paths_are_rejected(runtime_factory, field: str) -> None:
    _build, paths = runtime_factory
    kwargs: dict[str, object] = {
        "python_path": sys.executable,
        "model_path": paths["model"],
        "worker_script": paths["worker"],
        "manifest_path": paths["manifest"],
        "schema_path": paths["schema"],
        "qualified_identity": IDENTITY,
    }
    kwargs[field] = "relative/path"
    with pytest.raises(BrainError) as raised:
        flash_runtime.MlxFlashIntentRuntime(**kwargs)
    assert raised.value.code == "FLASH_RUNTIME_CONFIG"


def test_symlinked_model_and_worker_are_rejected(runtime_factory) -> None:
    _build, paths = runtime_factory
    model_link = paths["model"].parent / "model-link"
    model_link.symlink_to(paths["model"], target_is_directory=True)
    with pytest.raises(BrainError) as raised:
        flash_runtime.MlxFlashIntentRuntime(
            python_path=sys.executable,
            model_path=model_link,
            worker_script=paths["worker"],
            manifest_path=paths["manifest"],
            schema_path=paths["schema"],
            qualified_identity=IDENTITY,
        )
    assert raised.value.code == "FLASH_RUNTIME_CONFIG"

    worker_link = paths["worker"].parent / "worker-link.py"
    worker_link.symlink_to(paths["worker"])
    with pytest.raises(BrainError) as raised:
        flash_runtime.MlxFlashIntentRuntime(
            python_path=sys.executable,
            model_path=paths["model"],
            worker_script=worker_link,
            manifest_path=paths["manifest"],
            schema_path=paths["schema"],
            qualified_identity=IDENTITY,
        )
    assert raised.value.code == "FLASH_RUNTIME_CONFIG"


@pytest.mark.parametrize("timeout", [0, -1, 601, float("nan"), float("inf"), True])
def test_timeout_bound_is_enforced(runtime_factory, timeout: float) -> None:
    build, _paths = runtime_factory
    with pytest.raises(BrainError) as raised:
        build(timeout_seconds=timeout)
    assert raised.value.code == "FLASH_RUNTIME_CONFIG"


def test_injected_identity_is_exactly_pinned(runtime_factory) -> None:
    build, paths = runtime_factory
    for key, bad in (
        ("status", "candidate"),
        ("model_revision", "other"),
        ("schema_sha256", "other"),
        ("decoder", "json"),
    ):
        identity = dict(IDENTITY)
        identity[key] = bad
        with pytest.raises(BrainError) as raised:
            flash_runtime.MlxFlashIntentRuntime(
                python_path=sys.executable,
                model_path=paths["model"],
                worker_script=paths["worker"],
                manifest_path=paths["manifest"],
                schema_path=paths["schema"],
                qualified_identity=identity,
            )
        assert raised.value.code == "FLASH_RUNTIME_CONFIG"


def test_close_stalled_worker_is_bounded_and_leaves_no_orphan(
    runtime_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    build, _paths = runtime_factory
    monkeypatch.setattr(flash_runtime, "TERMINATE_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(flash_runtime, "KILL_WAIT_SECONDS", 1.0)
    runtime = build("ignore_term", timeout_seconds=30.0)
    errors: list[Exception] = []

    def call() -> None:
        try:
            runtime.compile(_request())
        except Exception as error:  # pragma: no cover - assertion below reports it
            errors.append(error)

    thread = threading.Thread(target=call)
    thread.start()
    process = _wait_for_process(runtime)
    time.sleep(0.05)
    started = time.monotonic()
    runtime.close()
    elapsed = time.monotonic() - started
    thread.join(timeout=2.0)
    assert elapsed < 1.5
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], BrainError)
    assert errors[0].code == "FLASH_RUNTIME_DIED"
    _assert_process_group_gone(process.pid)
    with pytest.raises(BrainError) as raised:
        runtime.compile(_request())
    assert raised.value.code == "FLASH_RUNTIME_CLOSED"
