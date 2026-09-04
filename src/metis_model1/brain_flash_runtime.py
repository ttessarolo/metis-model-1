"""Persistent, schema-constrained MLX intent compiler for Metis Brain.

The Flash worker is a second, independently supervised local process.  It
loads one pinned Gemma checkpoint at Brain startup and may only return the
closed Intent IR validated in :mod:`metis_model1.brain_intent_ir`.  It never
produces Metis source and it never replaces retrieval, grounding or compiler
authority.
"""

from __future__ import annotations

import json
import math
import os
import selectors
import signal
import subprocess
import threading
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from metis_model1 import initial_local_qlora_runtime as qualified_runtime
from metis_model1.brain_intent_ir import (
    FLASH_INTENT_SCHEMA_PATH,
    FLASH_INTENT_SCHEMA_SHA256,
    MAX_FLASH_GENERATION_TOKENS,
    MAX_FLASH_METRIC_COUNT,
    IntentCompileRequest,
    IntentCompileResult,
    IntentIR,
    validate_intent_ir_schema,
    validate_intent_metrics,
)
from metis_model1.brain_mlx_runtime import (
    _canonical_directory,
    _canonical_file,
    _worker_environment,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FLASH_MANIFEST_PATH = PROJECT_ROOT / "manifests/brain-flash-gemma4-e4b-v1.json"
FLASH_WORKER_PATH = Path(__file__).with_name("brain_flash_worker.py")
QUALIFICATION_LOCK_PATH = PROJECT_ROOT / "qualification/uv.lock"
EXPECTED_MODEL_REVISION = "475b9088d29754a3379866cf5aeb6b41acd313c2"
EXPECTED_DECODER = "llguidance-1.8.0"
# These two identities are filled only after the worker and candidate manifest
# have passed the local qualification roster.  Production construction fails
# closed while either pin is absent or differs.
FLASH_WORKER_SHA256 = "sha256:12a7966ec8acd8f4386f6df57fd1165a1456c152f4707e3d5b2a6cee4b4f8b69"
FLASH_MANIFEST_SHA256 = "sha256:195b2af4ce0b34e57643a7f64cc7493968334e9cfc03f0059850e4b5f1ae5507"
MAX_WORKER_REQUEST_BYTES = 600 * 1024
MAX_WORKER_RESPONSE_BYTES = 600 * 1024
MAX_STDERR_BYTES = 128 * 1024
MAX_REQUESTS_PER_PROCESS = 240
DEFAULT_TIMEOUT_SECONDS = 60.0
TERMINATE_GRACE_SECONDS = 5.0
KILL_WAIT_SECONDS = 5.0


def _runtime_error(code: str, status: int, message: str) -> BrainError:
    return BrainError(code, status, message)


def _strict_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON member")
            value[key] = item
        return value

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as error:
        raise _runtime_error(
            "FLASH_RESPONSE_INVALID", 502, f"local Flash {label} is invalid"
        ) from error
    if not isinstance(value, dict):
        raise _runtime_error("FLASH_RESPONSE_INVALID", 502, f"local Flash {label} is invalid")
    return value


def _safe_tracked_object(path: Path, *, maximum: int) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise _runtime_error(
            "FLASH_RUNTIME_CONFIG", 500, "Flash qualification metadata is unavailable"
        ) from error
    if not raw or len(raw) > maximum:
        raise _runtime_error("FLASH_RUNTIME_CONFIG", 500, "Flash qualification metadata is invalid")
    try:
        value = _strict_object(raw, label="qualification metadata")
    except BrainError as error:
        raise _runtime_error(
            "FLASH_RUNTIME_CONFIG", 500, "Flash qualification metadata is invalid"
        ) from error
    return value, raw


def _verify_qualified_manifest(path: Path) -> dict[str, Any]:
    value, raw = _safe_tracked_object(path, maximum=1024 * 1024)
    if FLASH_MANIFEST_SHA256 == "UNQUALIFIED" or bytes_sha256(raw) != FLASH_MANIFEST_SHA256:
        raise _runtime_error("FLASH_RUNTIME_CONFIG", 500, "qualified Flash manifest differs")
    model = value.get("model")
    runtime = value.get("runtime")
    schema = value.get("intent_schema")
    if (
        value.get("schema_version") != 1
        or value.get("status") != "qualified"
        or value.get("role") != "metis_brain_flash_intent_compiler"
        or not isinstance(model, dict)
        or model.get("repository") != "mlx-community/gemma-4-e4b-it-4bit"
        or model.get("revision") != EXPECTED_MODEL_REVISION
        or model.get("upstream_repository") != "google/gemma-4-E4B-it"
        or model.get("upstream_revision") != "fee6332c1abaafb77f6f9624236c63aa2f1d0187"
        or model.get("license") != "gemma"
        or model.get("distribution_gate") != "open"
        or model.get("model_type") != "gemma4"
        or not isinstance(runtime, dict)
        or runtime.get("decoder") != EXPECTED_DECODER
        or runtime.get("worker_sha256") != FLASH_WORKER_SHA256
        or runtime.get("network") != "denied"
        or not isinstance(schema, dict)
        or schema.get("canonical_sha256") != FLASH_INTENT_SCHEMA_SHA256
    ):
        raise _runtime_error("FLASH_RUNTIME_CONFIG", 500, "qualified Flash manifest is invalid")
    try:
        lock_sha256 = bytes_sha256(QUALIFICATION_LOCK_PATH.read_bytes()).removeprefix("sha256:")
    except OSError as error:
        raise _runtime_error(
            "FLASH_RUNTIME_CONFIG", 500, "Flash qualification lock is unavailable"
        ) from error
    if runtime.get("qualification_lock_sha256") != lock_sha256:
        raise _runtime_error("FLASH_RUNTIME_CONFIG", 500, "Flash qualification lock differs")
    return value


class MlxFlashIntentRuntime:
    """One persistent, sandboxed Flash JSONL worker."""

    def __init__(
        self,
        *,
        python_path: Path | str,
        model_path: Path | str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        worker_script: Path | str | None = None,
        manifest_path: Path | str | None = None,
        schema_path: Path | str | None = None,
        qualified_identity: dict[str, Any] | None = None,
    ) -> None:
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds):
            raise _runtime_error("FLASH_RUNTIME_CONFIG", 500, "Flash timeout is invalid")
        if not 0 < float(timeout_seconds) <= 600:
            raise _runtime_error("FLASH_RUNTIME_CONFIG", 500, "Flash timeout is outside its bound")
        try:
            self._python_path = _canonical_file(
                python_path, label="Flash python", allow_symlink=True
            )
            self._model_path = _canonical_directory(model_path, label="Flash model")
            self._production_worker = worker_script is None
            self._worker_script = _canonical_file(
                worker_script or FLASH_WORKER_PATH, label="Flash worker"
            )
            self._manifest_path = _canonical_file(
                manifest_path or FLASH_MANIFEST_PATH, label="Flash manifest"
            )
            self._schema_path = _canonical_file(
                schema_path or FLASH_INTENT_SCHEMA_PATH, label="Flash schema"
            )
        except BrainError as error:
            raise _runtime_error(
                "FLASH_RUNTIME_CONFIG", 500, "Flash runtime path is invalid"
            ) from error
        if not qualified_runtime.SANDBOX_EXEC.is_file():
            raise _runtime_error("FLASH_RUNTIME_CONFIG", 500, "Flash sandbox is unavailable")
        self._verify_worker()
        identity = (
            _verify_qualified_manifest(self._manifest_path)
            if qualified_identity is None
            else dict(qualified_identity)
        )
        if qualified_identity is not None:
            self._verify_injected_identity(identity)
        schema, _raw_schema = _safe_tracked_object(self._schema_path, maximum=256 * 1024)
        if bytes_sha256(canonical_json(schema)) != FLASH_INTENT_SCHEMA_SHA256:
            raise _runtime_error("FLASH_RUNTIME_CONFIG", 500, "Flash intent schema differs")
        self._model_revision = EXPECTED_MODEL_REVISION
        self._schema_sha256 = FLASH_INTENT_SCHEMA_SHA256
        self._decoder = EXPECTED_DECODER
        self._timeout_seconds = float(timeout_seconds)
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_overflow = False
        self._request_lock = threading.Lock()
        self._closed = False
        self._broken = False
        self._process_requests = 0
        self._warmup_status = "cold"
        self._warmup_duration_ms: int | None = None
        self._warmup_worker_load_ms: int | None = None

    @staticmethod
    def _verify_injected_identity(value: dict[str, Any]) -> None:
        if value != {
            "status": "qualified",
            "model_revision": EXPECTED_MODEL_REVISION,
            "schema_sha256": FLASH_INTENT_SCHEMA_SHA256,
            "decoder": EXPECTED_DECODER,
        }:
            raise _runtime_error("FLASH_RUNTIME_CONFIG", 500, "injected Flash identity is invalid")

    @property
    def model_loaded(self) -> bool:
        with self._request_lock:
            return self._process is not None and self._process.poll() is None and not self._broken

    @property
    def model_revision(self) -> str:
        return self._model_revision

    @property
    def schema_sha256(self) -> str:
        return self._schema_sha256

    @property
    def decoder(self) -> str:
        return self._decoder

    @property
    def warmup_status(self) -> str:
        with self._request_lock:
            return self._warmup_status

    @property
    def warmup_duration_ms(self) -> int | None:
        with self._request_lock:
            return self._warmup_duration_ms

    @property
    def warmup_worker_load_ms(self) -> int | None:
        with self._request_lock:
            return self._warmup_worker_load_ms

    def warmup(self) -> dict[str, int | str]:
        with self._request_lock:
            self._ensure_open()
            self._ensure_process()
            return self._warmup_payload()

    def _warmup_payload(self) -> dict[str, int | str]:
        if (
            self._warmup_status != "ready"
            or self._warmup_duration_ms is None
            or self._warmup_worker_load_ms is None
        ):
            raise _runtime_error("FLASH_RUNTIME_BROKEN", 503, "local Flash warmup is unavailable")
        return {
            "status": "ready",
            "duration_ms": self._warmup_duration_ms,
            "worker_load_ms": self._warmup_worker_load_ms,
        }

    def compile(self, request: IntentCompileRequest) -> IntentCompileResult:
        request_id = str(uuid.uuid4())
        raw = (
            canonical_json(
                {
                    "request_id": request_id,
                    "operation": "compile",
                    "instruction": request.instruction,
                    "intent": request.intent,
                    "target_mode": request.target_mode,
                    "max_tokens": MAX_FLASH_GENERATION_TOKENS,
                }
            )
            + b"\n"
        )
        if len(raw) > MAX_WORKER_REQUEST_BYTES:
            raise _runtime_error(
                "FLASH_INPUT_TOO_LARGE", 413, "Flash request exceeds the worker limit"
            )
        with self._request_lock:
            self._ensure_open()
            if request.cancellation is not None and request.cancellation.is_set():
                raise _runtime_error(
                    "FLASH_COMPILATION_CANCELLED", 409, "local Flash compilation was cancelled"
                )
            process = self._ensure_process(request.cancellation)
            try:
                line = self._exchange(process, raw, self._timeout_seconds, request.cancellation)
                response = self._parse_compile_response(line, request_id, request)
            except BrainError as error:
                if error.code == "FLASH_COMPILATION_CANCELLED":
                    self._reset_cancelled(process)
                elif (
                    error.code == "FLASH_INTENT_REJECTED"
                    and process.poll() is None
                    and not self._stderr_overflow
                ):
                    # The exact JSONL envelope has been consumed and the
                    # qualified worker is still synchronized. A host-side
                    # semantic rejection is request-local: discard it, count
                    # it against the recycle bound and keep the warm worker.
                    # Protocol, identity, telemetry and transport failures
                    # still take the fatal branch below.
                    self._process_requests += 1
                    self._warmup_status = "ready"
                else:
                    self._mark_broken(process)
                raise
            except (BrokenPipeError, OSError) as error:
                self._mark_broken(process)
                raise _runtime_error(
                    "FLASH_RUNTIME_DIED", 503, "local Flash worker stopped"
                ) from error
            self._process_requests += 1
            self._warmup_status = "ready"
            self._warmup_worker_load_ms = int(response.metrics["worker_load_ms"])
            return response

    def close(self) -> None:
        process = self._process
        if process is not None:
            self._terminate(process)
        with self._request_lock:
            if self._closed:
                return
            self._closed = True
            self._warmup_status = "closed"
            process = self._process
            self._process = None
            self._process_requests = 0
            if process is not None:
                self._terminate(process)

    def _ensure_open(self) -> None:
        if self._closed:
            raise _runtime_error("FLASH_RUNTIME_CLOSED", 503, "local Flash runtime is closed")
        if self._broken:
            raise _runtime_error("FLASH_RUNTIME_BROKEN", 503, "local Flash worker is unavailable")

    def _ensure_process(
        self, cancellation: threading.Event | None = None
    ) -> subprocess.Popen[bytes]:
        process = self._process
        if process is not None:
            if process.poll() is None:
                if self._process_requests < MAX_REQUESTS_PER_PROCESS:
                    if self._warmup_status != "ready":
                        self._mark_broken(process)
                        raise _runtime_error(
                            "FLASH_RUNTIME_BROKEN", 503, "local Flash warmup is unavailable"
                        )
                    return process
                self._terminate(process)
                self._process = None
                self._process_requests = 0
                self._warmup_status = "cold"
                self._warmup_duration_ms = None
                self._warmup_worker_load_ms = None
            else:
                self._mark_broken(process)
                raise _runtime_error("FLASH_RUNTIME_DIED", 503, "local Flash worker stopped")
        for path in (
            qualified_runtime.EVALUATION_CACHE_ROOT,
            qualified_runtime.EVALUATION_CACHE_ROOT / "home",
            qualified_runtime.EVALUATION_CACHE_ROOT / "tmp",
        ):
            path.mkdir(parents=True, exist_ok=True)
        self._verify_worker()
        command = [
            str(qualified_runtime.SANDBOX_EXEC),
            "-p",
            qualified_runtime.EVALUATION_SANDBOX_POLICY,
            str(self._python_path),
            str(self._worker_script),
            "worker",
            "--model",
            str(self._model_path),
            "--manifest",
            str(self._manifest_path),
            "--schema",
            str(self._schema_path),
        ]
        warmup_started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                env=_worker_environment(),
                shell=False,
                start_new_session=True,
                bufsize=0,
            )
        except (OSError, ValueError) as error:
            self._broken = True
            self._warmup_status = "failed"
            raise _runtime_error(
                "FLASH_RUNTIME_START_FAILED", 503, "local Flash worker could not start"
            ) from error
        self._process = process
        assert process.stdin is not None
        assert process.stdout is not None
        try:
            os.set_blocking(process.stdin.fileno(), False)
            os.set_blocking(process.stdout.fileno(), False)
        except OSError as error:
            self._mark_broken(process)
            raise _runtime_error(
                "FLASH_RUNTIME_START_FAILED", 503, "local Flash pipes are unavailable"
            ) from error
        self._stderr_overflow = False
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(process,),
            daemon=True,
            name="metis-flash-stderr",
        )
        self._stderr_thread.start()
        request_id = str(uuid.uuid4())
        raw = canonical_json({"request_id": request_id, "operation": "warmup"}) + b"\n"
        try:
            line = self._exchange(process, raw, self._timeout_seconds, cancellation)
            response = self._parse_warmup_response(line, request_id)
        except BrainError as error:
            if error.code == "FLASH_COMPILATION_CANCELLED":
                self._reset_cancelled(process)
            else:
                self._mark_broken(process)
            raise
        except (BrokenPipeError, OSError) as error:
            self._mark_broken(process)
            raise _runtime_error("FLASH_RUNTIME_DIED", 503, "local Flash worker stopped") from error
        self._warmup_status = "ready"
        self._warmup_duration_ms = max(0, int((time.monotonic() - warmup_started) * 1000))
        self._warmup_worker_load_ms = response["worker_load_ms"]
        return process

    def _verify_worker(self) -> None:
        if not self._production_worker:
            return
        try:
            digest = bytes_sha256(self._worker_script.read_bytes())
        except OSError as error:
            raise _runtime_error(
                "FLASH_RUNTIME_CONFIG", 500, "qualified Flash worker is unavailable"
            ) from error
        if FLASH_WORKER_SHA256 == "UNQUALIFIED" or digest != FLASH_WORKER_SHA256:
            raise _runtime_error("FLASH_RUNTIME_CONFIG", 500, "qualified Flash worker differs")

    def _drain_stderr(self, process: subprocess.Popen[bytes]) -> None:
        stream = process.stderr
        if stream is None:
            return
        total = 0
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                total += len(chunk)
                if total > MAX_STDERR_BYTES:
                    self._stderr_overflow = True
        except OSError:
            return

    @staticmethod
    def _exchange(
        process: subprocess.Popen[bytes],
        raw: bytes,
        timeout: float,
        cancellation: threading.Event | None,
    ) -> bytes:
        assert process.stdin is not None
        assert process.stdout is not None
        stdin_fd = process.stdin.fileno()
        stdout_fd = process.stdout.fileno()
        pending = memoryview(raw)
        response = bytearray()
        deadline = time.monotonic() + timeout
        selector = selectors.DefaultSelector()
        try:
            selector.register(stdin_fd, selectors.EVENT_WRITE, "stdin")
            selector.register(stdout_fd, selectors.EVENT_READ, "stdout")
            while True:
                if cancellation is not None and cancellation.is_set():
                    raise _runtime_error(
                        "FLASH_COMPILATION_CANCELLED",
                        409,
                        "local Flash compilation was cancelled",
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _runtime_error(
                        "FLASH_RUNTIME_TIMEOUT", 504, "local Flash worker timed out"
                    )
                wait = min(remaining, 0.1) if cancellation is not None else remaining
                events = selector.select(wait)
                if not events:
                    continue
                for key, _events in events:
                    if key.data == "stdin":
                        try:
                            written = os.write(stdin_fd, pending)
                        except BlockingIOError:
                            continue
                        except OSError as error:
                            raise _runtime_error(
                                "FLASH_RUNTIME_DIED", 503, "local Flash worker stopped"
                            ) from error
                        pending = pending[written:]
                        if not pending:
                            selector.unregister(stdin_fd)
                    else:
                        try:
                            chunk = os.read(stdout_fd, 8192)
                        except BlockingIOError:
                            continue
                        except OSError as error:
                            raise _runtime_error(
                                "FLASH_RUNTIME_DIED", 503, "local Flash worker stopped"
                            ) from error
                        if not chunk:
                            raise _runtime_error(
                                "FLASH_RUNTIME_DIED", 503, "local Flash worker stopped"
                            )
                        response.extend(chunk)
                        if len(response) > MAX_WORKER_RESPONSE_BYTES:
                            raise _runtime_error(
                                "FLASH_RESPONSE_INVALID", 502, "local Flash response is oversized"
                            )
                        newline = response.find(b"\n")
                        if newline >= 0:
                            if newline != len(response) - 1:
                                raise _runtime_error(
                                    "FLASH_RESPONSE_INVALID",
                                    502,
                                    "local Flash response contains trailing data",
                                )
                            return bytes(response)
        except (OSError, ValueError) as error:
            raise _runtime_error("FLASH_RUNTIME_DIED", 503, "local Flash worker stopped") from error
        finally:
            selector.close()

    def _parse_warmup_response(self, line: bytes, request_id: str) -> dict[str, Any]:
        value = _strict_object(line, label="warmup response")
        if (
            set(value)
            != {
                "schema_version",
                "request_id",
                "status",
                "worker_load_ms",
                "model_revision",
                "schema_sha256",
                "decoder",
            }
            or value["schema_version"] != 1
            or value["request_id"] != request_id
            or value["status"] != "ready"
            or value["model_revision"] != self._model_revision
            or value["schema_sha256"] != self._schema_sha256
            or value["decoder"] != self._decoder
            or type(value["worker_load_ms"]) is not int
            or not 0 <= value["worker_load_ms"] <= MAX_FLASH_METRIC_COUNT
            or self._stderr_overflow
        ):
            raise _runtime_error(
                "FLASH_RESPONSE_INVALID", 502, "local Flash warmup response is invalid"
            )
        return value

    def _parse_compile_response(
        self, line: bytes, request_id: str, request: IntentCompileRequest
    ) -> IntentCompileResult:
        value = _strict_object(line, label="response")
        if (
            set(value)
            != {
                "schema_version",
                "request_id",
                "intent_ir",
                "model_revision",
                "schema_sha256",
                "decoder",
                "metrics",
            }
            or value["schema_version"] != 1
            or value["request_id"] != request_id
            or value["model_revision"] != self._model_revision
            or value["schema_sha256"] != self._schema_sha256
            or value["decoder"] != self._decoder
            or not isinstance(value["metrics"], dict)
            or self._stderr_overflow
        ):
            raise _runtime_error(
                "FLASH_RESPONSE_INVALID", 502, "local Flash response schema is invalid"
            )
        try:
            validate_intent_ir_schema(value["intent_ir"])
            validate_intent_metrics(value["metrics"])
        except BrainError as error:
            raise _runtime_error(
                "FLASH_RESPONSE_INVALID", 502, "local Flash response is invalid"
            ) from error
        try:
            intent_ir = IntentIR.parse(value["intent_ir"], request=request)
        except BrainError as error:
            raise _runtime_error(
                "FLASH_INTENT_REJECTED", 502, "local Flash intent was rejected"
            ) from error
        try:
            return IntentCompileResult(
                intent_ir=intent_ir,
                model_revision=value["model_revision"],
                schema_sha256=value["schema_sha256"],
                decoder=value["decoder"],
                metrics=value["metrics"],
            )
        except BrainError as error:
            raise _runtime_error(
                "FLASH_RESPONSE_INVALID", 502, "local Flash response is invalid"
            ) from error

    def _mark_broken(self, process: subprocess.Popen[bytes]) -> None:
        self._broken = True
        self._warmup_status = "failed"
        self._warmup_duration_ms = None
        self._warmup_worker_load_ms = None
        self._process_requests = 0
        if self._process is process:
            self._process = None
        self._terminate(process)

    def _reset_cancelled(self, process: subprocess.Popen[bytes]) -> None:
        if self._process is process:
            self._process = None
        self._process_requests = 0
        self._broken = False
        self._warmup_status = "cold"
        self._warmup_duration_ms = None
        self._warmup_worker_load_ms = None
        self._terminate(process)

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            with suppress(OSError, ProcessLookupError):
                process.terminate()
        try:
            process.wait(timeout=TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                with suppress(OSError, ProcessLookupError):
                    process.kill()
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=KILL_WAIT_SECONDS)


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "FLASH_MANIFEST_PATH",
    "FLASH_WORKER_PATH",
    "MlxFlashIntentRuntime",
]
