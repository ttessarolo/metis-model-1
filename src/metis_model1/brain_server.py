"""Authenticated numeric-loopback HTTP service for Metis Brain."""

from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import math
import os
import secrets
import signal
import stat
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from metis_model1.brain_context import TenantRegistry
from metis_model1.brain_flash_runtime import MlxFlashIntentRuntime
from metis_model1.brain_mlx_runtime import MAX_PREFIX_CACHE_TOKENS, MlxBrainModelRuntime
from metis_model1.brain_model_runtime import MAX_TELEMETRY_COUNT, UnavailableModelRuntime
from metis_model1.brain_protocol import (
    MAX_JSON_BYTES,
    BrainError,
    bounded_identifier,
    canonical_json,
    capability_set,
    exact_fields,
    parse_json_object,
    revision,
)
from metis_model1.brain_retrieval import SnapshotRetriever
from metis_model1.brain_semantic_retrieval import Schema2SnapshotRetriever
from metis_model1.brain_sessions import ClientPolicy, SessionLimits, SessionManager
from metis_model1.brain_tools import (
    BrainCompiler,
    PinnedCatalogProjectionLoader,
    validate_compile_request,
)
from metis_model1.brain_turns import ClarificationAnswerRequest, TurnRequest, TurnStore

MAX_CONFIG_BYTES = 1024 * 1024
MAX_HTTP_WORKERS = 64
REQUEST_SOCKET_TIMEOUT_SECONDS = 15.0
MODEL_WARMUP_POLICIES = frozenset({"lazy", "on_start"})
INTENT_COMPILER_MODES = frozenset({"assist_on_unresolved"})


@dataclass(frozen=True)
class BrainModelConfig:
    python_path: Path
    model_path: Path
    adapter_path: Path
    timeout_seconds: float
    warmup: str = "lazy"


@dataclass(frozen=True)
class BrainRetrievalConfig:
    schema2: bool


@dataclass(frozen=True)
class BrainIntentCompilerConfig:
    python_path: Path
    model_path: Path
    timeout_seconds: float
    warmup: str
    mode: str


@dataclass(frozen=True)
class BrainConfig:
    host: str
    port: int
    runtime_root: Path
    metis_git_root: Path
    node_path: Path
    compiler_concurrency: int
    tenant_grants: tuple[tuple[str, str, Path], ...]
    client_policies: tuple[ClientPolicy, ...]
    limits: SessionLimits
    model: BrainModelConfig | None = None
    retrieval: BrainRetrievalConfig | None = None
    intent_compiler: BrainIntentCompilerConfig | None = None


def _safe_config_bytes(path: Path) -> bytes:
    if not path.is_absolute() or any(part.startswith(".env") for part in path.parts):
        raise BrainError("INVALID_CONFIG", 500, "config path must be absolute and non-secret")
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size > MAX_CONFIG_BYTES
        ):
            raise BrainError("INVALID_CONFIG", 500, "config is not a bounded regular file")
        raw = os.read(descriptor, opened.st_size + 1)
        after = os.fstat(descriptor)
        named_after = path.lstat()
    except BrainError:
        raise
    except OSError as error:
        raise BrainError("INVALID_CONFIG", 500, "config is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity = lambda value: (  # noqa: E731 - compact stable identity
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if (
        identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(named_after)
        or len(raw) != opened.st_size
    ):
        raise BrainError("INVALID_CONFIG", 500, "config changed while it was read")
    return raw


def _config_path(
    value: Any,
    *,
    label: str,
    may_create: bool = False,
    allow_symlink: bool = False,
) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise BrainError("INVALID_CONFIG", 500, f"{label} is invalid")
    path = Path(value)
    if not path.is_absolute() or any(part.startswith(".env") for part in path.parts):
        raise BrainError("INVALID_CONFIG", 500, f"{label} must be an absolute non-secret path")
    if may_create:
        parent = path.parent.resolve(strict=True)
        return parent / path.name
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise BrainError("INVALID_CONFIG", 500, f"{label} is unavailable") from error
    if any(part.startswith(".env") for part in resolved.parts):
        raise BrainError("INVALID_CONFIG", 500, f"{label} must be an absolute non-secret path")
    if resolved != path and not allow_symlink:
        raise BrainError("INVALID_CONFIG", 500, f"{label} must be canonical")
    return path if allow_symlink else resolved


def load_brain_config(path: Path) -> BrainConfig:
    value = parse_json_object(_safe_config_bytes(Path(path)), label="config")
    exact_fields(
        value,
        required={"schema_version", "server", "toolchain", "tenants", "clients", "limits"},
        optional={"model", "retrieval", "intent_compiler"},
        label="config",
    )
    if value["schema_version"] != 1:
        raise BrainError("INVALID_CONFIG", 500, "config schema version is unsupported")

    server = value["server"]
    toolchain = value["toolchain"]
    limits_value = value["limits"]
    if (
        not isinstance(server, dict)
        or not isinstance(toolchain, dict)
        or not isinstance(limits_value, dict)
    ):
        raise BrainError("INVALID_CONFIG", 500, "config sections must be objects")
    exact_fields(server, required={"host", "port", "runtime_root"}, label="server config")
    exact_fields(
        toolchain,
        required={"metis_git_root", "node_path", "compiler_concurrency"},
        label="toolchain config",
    )
    exact_fields(
        limits_value,
        required={"global_sessions", "sessions_per_client", "sessions_per_tenant"},
        label="limits config",
    )
    model_value = value.get("model")
    retrieval_value = value.get("retrieval")
    intent_compiler_value = value.get("intent_compiler")
    model: BrainModelConfig | None = None
    retrieval: BrainRetrievalConfig | None = None
    intent_compiler: BrainIntentCompilerConfig | None = None
    if "model" in value:
        if not isinstance(model_value, dict):
            raise BrainError("INVALID_CONFIG", 500, "model config must be an object")
        exact_fields(
            model_value,
            required={"python_path", "model_path", "adapter_path", "timeout_seconds"},
            optional={"warmup"},
            label="model config",
        )
        timeout_seconds = model_value["timeout_seconds"]
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 600
        ):
            raise BrainError("INVALID_CONFIG", 500, "model timeout is invalid")
        warmup = model_value.get("warmup", "lazy")
        if not isinstance(warmup, str) or warmup not in MODEL_WARMUP_POLICIES:
            raise BrainError("INVALID_CONFIG", 500, "model warmup policy is invalid")
        model = BrainModelConfig(
            python_path=_config_path(
                model_value["python_path"], label="model python path", allow_symlink=True
            ),
            model_path=_config_path(model_value["model_path"], label="model path"),
            adapter_path=_config_path(model_value["adapter_path"], label="adapter path"),
            timeout_seconds=float(timeout_seconds),
            warmup=warmup,
        )
    if "retrieval" in value:
        if not isinstance(retrieval_value, dict):
            raise BrainError("INVALID_CONFIG", 500, "retrieval config must be an object")
        exact_fields(retrieval_value, required={"schema2"}, label="retrieval config")
        if type(retrieval_value["schema2"]) is not bool:
            raise BrainError("INVALID_CONFIG", 500, "retrieval schema2 must be boolean")
        retrieval = BrainRetrievalConfig(schema2=retrieval_value["schema2"])
    if "intent_compiler" in value:
        if not isinstance(intent_compiler_value, dict):
            raise BrainError("INVALID_CONFIG", 500, "intent compiler config must be an object")
        exact_fields(
            intent_compiler_value,
            required={"python_path", "model_path", "timeout_seconds", "warmup", "mode"},
            label="intent compiler config",
        )
        timeout_seconds = intent_compiler_value["timeout_seconds"]
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 600
        ):
            raise BrainError("INVALID_CONFIG", 500, "intent compiler timeout is invalid")
        if intent_compiler_value["warmup"] != "on_start":
            raise BrainError(
                "INVALID_CONFIG", 500, "intent compiler must warm before server binding"
            )
        if intent_compiler_value["mode"] not in INTENT_COMPILER_MODES:
            raise BrainError("INVALID_CONFIG", 500, "intent compiler mode is invalid")
        intent_compiler = BrainIntentCompilerConfig(
            python_path=_config_path(
                intent_compiler_value["python_path"],
                label="intent compiler python path",
                allow_symlink=True,
            ),
            model_path=_config_path(
                intent_compiler_value["model_path"], label="intent compiler model path"
            ),
            timeout_seconds=float(timeout_seconds),
            warmup="on_start",
            mode=intent_compiler_value["mode"],
        )
    if model is not None and (retrieval is None or not retrieval.schema2):
        raise BrainError("INVALID_CONFIG", 500, "model configuration requires schema2 retrieval")
    if intent_compiler is not None and (retrieval is None or not retrieval.schema2):
        raise BrainError(
            "INVALID_CONFIG", 500, "intent compiler configuration requires schema2 retrieval"
        )
    if server["host"] != "127.0.0.1":
        raise BrainError("INVALID_CONFIG", 500, "server host must be numeric IPv4 loopback")
    if type(server["port"]) is not int or not 0 <= server["port"] <= 65535:
        raise BrainError("INVALID_CONFIG", 500, "server port is invalid")
    if type(toolchain["compiler_concurrency"]) is not int:
        raise BrainError("INVALID_CONFIG", 500, "compiler concurrency is invalid")

    tenants_value = value["tenants"]
    clients_value = value["clients"]
    if not isinstance(tenants_value, list) or not tenants_value:
        raise BrainError("INVALID_CONFIG", 500, "tenants must be a non-empty list")
    if not isinstance(clients_value, list) or not clients_value:
        raise BrainError("INVALID_CONFIG", 500, "clients must be a non-empty list")
    tenant_grants: list[tuple[str, str, Path]] = []
    for item in tenants_value:
        if not isinstance(item, dict):
            raise BrainError("INVALID_CONFIG", 500, "tenant grant must be an object")
        exact_fields(item, required={"alias", "tenant_id", "root"}, label="tenant grant")
        alias = bounded_identifier(item["alias"], kind="tenant")
        tenant_id = item["tenant_id"]
        if not isinstance(tenant_id, str) or not tenant_id or len(tenant_id) > 128:
            raise BrainError("INVALID_CONFIG", 500, "tenant ID is invalid")
        tenant_grants.append((alias, tenant_id, _config_path(item["root"], label="tenant root")))

    policies: list[ClientPolicy] = []
    for item in clients_value:
        if not isinstance(item, dict):
            raise BrainError("INVALID_CONFIG", 500, "client policy must be an object")
        exact_fields(
            item,
            required={"client_id", "tenant_aliases", "capabilities"},
            label="client policy",
        )
        aliases = item["tenant_aliases"]
        if not isinstance(aliases, list) or not aliases or len(aliases) > len(tenant_grants):
            raise BrainError("INVALID_CONFIG", 500, "client tenant aliases are invalid")
        normalized_aliases = [bounded_identifier(alias, kind="tenant") for alias in aliases]
        if len(set(normalized_aliases)) != len(normalized_aliases):
            raise BrainError("INVALID_CONFIG", 500, "client tenant aliases are duplicated")
        policies.append(
            ClientPolicy(
                client_id=bounded_identifier(item["client_id"], kind="client"),
                tenant_aliases=frozenset(normalized_aliases),
                capabilities=capability_set(item["capabilities"]),
            )
        )

    try:
        limits = SessionLimits(**limits_value)
    except TypeError as error:
        raise BrainError("INVALID_CONFIG", 500, "session limits are invalid") from error
    return BrainConfig(
        host=server["host"],
        port=server["port"],
        runtime_root=_config_path(server["runtime_root"], label="runtime root", may_create=True),
        metis_git_root=_config_path(toolchain["metis_git_root"], label="Metis Git root"),
        node_path=_config_path(toolchain["node_path"], label="Node path"),
        compiler_concurrency=toolchain["compiler_concurrency"],
        tenant_grants=tuple(tenant_grants),
        client_policies=tuple(policies),
        limits=limits,
        model=model,
        retrieval=retrieval,
        intent_compiler=intent_compiler,
    )


class BrainRuntime:
    """One per-start private runtime and rotated bootstrap file."""

    def __init__(self, base: Path) -> None:
        raw_base = Path(base)
        if not raw_base.is_absolute():
            raise BrainError("INVALID_CONFIG", 500, "runtime root must be absolute")
        raw_base.mkdir(parents=True, exist_ok=True, mode=0o700)
        base = raw_base.resolve(strict=True)
        if base != raw_base:
            raise BrainError("INVALID_CONFIG", 500, "runtime root must be canonical")
        if base.is_symlink() or not base.is_dir():
            raise BrainError("INVALID_CONFIG", 500, "runtime root must be a real directory")
        os.chmod(base, 0o700)
        self.base = base
        self.run_dir = base / f"run-{os.getpid()}-{secrets.token_hex(8)}"
        self.bootstrap_file = self.run_dir / "bootstrap.token"
        token = secrets.token_urlsafe(32)
        descriptor: int | None = None
        try:
            self.run_dir.mkdir(mode=0o700)
            descriptor = os.open(
                self.bootstrap_file,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
            payload = (token + "\n").encode("ascii")
            if os.write(descriptor, payload) != len(payload):
                raise OSError("short bootstrap token write")
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.chmod(self.bootstrap_file, 0o600)
            self.bootstrap_digest = hashlib.sha256(token.encode("ascii")).digest()
            self._closed = False
        except BaseException:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)
            with suppress(OSError):
                self.bootstrap_file.unlink(missing_ok=True)
            with suppress(OSError):
                self.run_dir.rmdir()
            raise
        finally:
            token = ""

    def authenticate(self, token: str) -> bool:
        try:
            digest = hashlib.sha256(token.encode("ascii", "strict")).digest()
        except UnicodeEncodeError:
            return False
        return hmac.compare_digest(digest, self.bootstrap_digest)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.bootstrap_file.unlink(missing_ok=True)
        with suppress(OSError):
            self.run_dir.rmdir()


class BrainApplication:
    def __init__(
        self,
        *,
        runtime: BrainRuntime,
        manager: SessionManager,
        compiler: BrainCompiler,
        retriever: Any | None = None,
        model: Any | None = None,
        model_warmup_policy: str = "disabled",
        intent_compiler: Any | None = None,
    ) -> None:
        if model_warmup_policy not in {*MODEL_WARMUP_POLICIES, "disabled"}:
            raise BrainError("INVALID_CONFIG", 500, "model warmup policy is invalid")
        self.runtime = runtime
        self.manager = manager
        self.compiler = compiler
        self.retriever = retriever if retriever is not None else SnapshotRetriever()
        self.model = model if model is not None else UnavailableModelRuntime()
        self.model_warmup_policy = model_warmup_policy
        self.intent_compiler = intent_compiler
        self.turns = TurnStore(
            manager=manager,
            retriever=self.retriever,
            model=self.model,
            compiler=compiler,
            intent_compiler=intent_compiler,
        )

    def authenticate_bootstrap(self, token: str) -> None:
        if not self.runtime.authenticate(token):
            raise BrainError("BOOTSTRAP_UNAUTHORIZED", 401, "bootstrap authorization failed")

    def health(self) -> dict[str, Any]:
        metrics = self.manager.aggregate_metrics()
        metrics.update(self.turns.aggregate_metrics())
        warmup_status = "disabled"
        warmup_duration_ms: int | None = None
        warmup_worker_load_ms: int | None = None
        warmup_prefix_tokens: int | None = None
        prefix_cache_ready = False
        if self.model_warmup_policy != "disabled":
            reported_status = getattr(self.model, "warmup_status", "cold")
            if reported_status in {"cold", "ready", "failed", "closed"}:
                warmup_status = reported_status
            for attribute, target in (
                ("warmup_duration_ms", "duration"),
                ("warmup_worker_load_ms", "worker_load"),
            ):
                value = getattr(self.model, attribute, None)
                if type(value) is not int or not 0 <= value <= MAX_TELEMETRY_COUNT:
                    value = None
                if target == "duration":
                    warmup_duration_ms = value
                else:
                    warmup_worker_load_ms = value
            value = getattr(self.model, "warmup_prefix_tokens", None)
            if type(value) is int and 0 <= value <= MAX_TELEMETRY_COUNT:
                warmup_prefix_tokens = value
            prefix_cache_ready = getattr(self.model, "prefix_cache_ready", False) is True
        health = {
            "schema_version": 1,
            "status": (
                "ready"
                if self.intent_compiler is None
                or bool(getattr(self.intent_compiler, "model_loaded", False))
                else "unavailable"
            ),
            "service": "metis-brain",
            "protocol": "v1",
            "turn_schema_versions": [1, 2],
            "clarification_answer_schema_versions": [1],
            "compiler_configured": True,
            "compiler_executions": getattr(self.compiler, "execution_count", 0),
            "model_loaded": bool(getattr(self.model, "model_loaded", False)),
            "model_identity": {
                "model_revision": getattr(self.model, "model_revision", None),
                "adapter_sha256": getattr(self.model, "adapter_sha256", None),
            },
            "model_warmup": {
                "policy": self.model_warmup_policy,
                "status": warmup_status,
                "duration_ms": warmup_duration_ms,
                "worker_load_ms": warmup_worker_load_ms,
                "prefix_tokens": warmup_prefix_tokens,
                "prefix_cache_ready": prefix_cache_ready,
            },
            "semantic_retrieval": {
                "enabled": isinstance(self.retriever, Schema2SnapshotRetriever),
                "schema": 2 if isinstance(self.retriever, Schema2SnapshotRetriever) else None,
                "implementation": type(self.retriever).__name__,
            },
            "metrics": metrics,
        }
        if self.intent_compiler is not None:
            duration = getattr(self.intent_compiler, "warmup_duration_ms", None)
            worker_load = getattr(self.intent_compiler, "warmup_worker_load_ms", None)
            health["intent_compiler"] = {
                "enabled": True,
                "mode": "assist_on_unresolved",
                "model_loaded": bool(getattr(self.intent_compiler, "model_loaded", False)),
                "identity": {
                    "model_revision": getattr(self.intent_compiler, "model_revision", None),
                    "schema_sha256": getattr(self.intent_compiler, "schema_sha256", None),
                    "decoder": getattr(self.intent_compiler, "decoder", None),
                },
                "warmup": {
                    "policy": "on_start",
                    "status": getattr(self.intent_compiler, "warmup_status", "cold"),
                    "duration_ms": (
                        duration
                        if type(duration) is int and 0 <= duration <= MAX_TELEMETRY_COUNT
                        else None
                    ),
                    "worker_load_ms": (
                        worker_load
                        if type(worker_load) is int and 0 <= worker_load <= MAX_TELEMETRY_COUNT
                        else None
                    ),
                },
            }
        return health

    def close(self) -> None:
        try:
            self.turns.shutdown()
        finally:
            try:
                close = getattr(self.intent_compiler, "close", None)
                if callable(close):
                    close()
            finally:
                try:
                    close = getattr(self.model, "close", None)
                    if callable(close):
                        close()
                finally:
                    try:
                        close = getattr(self.retriever, "close", None)
                        if callable(close):
                            close()
                    finally:
                        close = getattr(self.compiler, "close", None)
                        if callable(close):
                            close()


class _ThreadingBrainHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], app: BrainApplication) -> None:
        self.app = app
        self._request_slots = threading.BoundedSemaphore(MAX_HTTP_WORKERS)
        super().__init__(address, BrainRequestHandler)

    def get_request(self) -> tuple[Any, Any]:
        request, client_address = super().get_request()
        request.settimeout(REQUEST_SOCKET_TIMEOUT_SECONDS)
        return request, client_address

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


class BrainRequestHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MetisBrain/1"
    sys_version = ""

    @property
    def app(self) -> BrainApplication:
        return self.server.app  # type: ignore[attr-defined,no-any-return]

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        del message, explain
        public_code = code if 400 <= code <= 599 else 500
        self._response(
            public_code,
            BrainError("HTTP_REJECTED", public_code, "HTTP request was rejected").payload(),
            write_body=self.command != "HEAD",
        )

    def _response(self, status: int, payload: dict[str, Any], *, write_body: bool = True) -> None:
        raw = canonical_json(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        if write_body:
            self.wfile.write(raw)
        self.close_connection = True

    def _guard_transport(self) -> str:
        split = urlsplit(self.path)
        if split.query or split.fragment or split.scheme or split.netloc:
            raise BrainError("INVALID_ROUTE", 404, "route is unavailable")
        origins = self.headers.get_all("Origin") or []
        cookies = self.headers.get_all("Cookie") or []
        authorizations = self.headers.get_all("Authorization") or []
        if origins:
            raise BrainError("BROWSER_ORIGIN_DENIED", 403, "browser-origin request is denied")
        if cookies:
            raise BrainError("COOKIE_DENIED", 400, "cookies are not accepted")
        if len(authorizations) > 1:
            raise BrainError("INVALID_HEADER", 400, "authorization header is duplicated")
        hosts = self.headers.get_all("Host") or []
        bound_port = self.server.server_address[1]  # type: ignore[attr-defined]
        if hosts != [f"127.0.0.1:{bound_port}"]:
            raise BrainError("HOST_DENIED", 400, "host is not the bound loopback address")
        return split.path

    def _body(self) -> dict[str, Any]:
        if self.headers.get_all("Transfer-Encoding"):
            raise BrainError("INVALID_BODY", 400, "transfer encoding is not accepted")
        if (self.headers.get_all("Content-Type") or []) != ["application/json"]:
            raise BrainError("INVALID_BODY", 415, "content type must be application/json")
        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) != 1:
            raise BrainError("INVALID_BODY", 400, "one content length is required")
        raw_length = lengths[0]
        if raw_length is None or not raw_length.isascii() or not raw_length.isdigit():
            raise BrainError("INVALID_BODY", 400, "content length is required")
        length = int(raw_length)
        if length < 1 or length > MAX_JSON_BYTES:
            raise BrainError("PAYLOAD_TOO_LARGE", 413, "request body exceeds the byte limit")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise BrainError("INVALID_BODY", 400, "request body is incomplete")
        return parse_json_object(raw)

    def _require_no_body(self) -> None:
        if self.headers.get_all("Transfer-Encoding"):
            raise BrainError("INVALID_BODY", 400, "transfer encoding is not accepted")
        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) > 1 or (lengths and lengths != ["0"]):
            raise BrainError("INVALID_BODY", 400, "request must not contain a body")

    def _bearer(self) -> str:
        values = self.headers.get_all("Authorization") or []
        value = values[0] if len(values) == 1 else None
        if value is None or not value.startswith("Bearer ") or len(value) > 512:
            raise BrainError("UNAUTHORIZED", 401, "bearer authorization is required")
        token = value.removeprefix("Bearer ")
        if not token or any(character.isspace() for character in token):
            raise BrainError("UNAUTHORIZED", 401, "bearer authorization is required")
        return token

    @staticmethod
    def _session_route(path: str, suffix: str = "") -> str | None:
        prefix = "/v1/sessions/"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None
        middle = path[len(prefix) : len(path) - len(suffix) if suffix else None]
        if not middle or "/" in middle:
            return None
        try:
            return bounded_identifier(middle, kind="session")
        except BrainError:
            return None

    @staticmethod
    def _turn_route(path: str, suffix: str = "") -> tuple[str, str] | None:
        prefix = "/v1/sessions/"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None
        middle = path[len(prefix) : len(path) - len(suffix) if suffix else None]
        parts = middle.split("/")
        if len(parts) != 3 or parts[1] != "turns":
            return None
        try:
            session_id = bounded_identifier(parts[0], kind="session")
        except BrainError:
            return None
        turn_id = parts[2]
        if not turn_id or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
            for character in turn_id
        ):
            return None
        return session_id, turn_id

    @staticmethod
    def _turn_collection_route(path: str) -> str | None:
        prefix = "/v1/sessions/"
        marker = "/turns"
        if not path.startswith(prefix) or not path.endswith(marker):
            return None
        middle = path[len(prefix) : -len(marker)]
        if not middle or "/" in middle:
            return None
        try:
            return bounded_identifier(middle, kind="session")
        except BrainError:
            return None

    def _dispatch_get(self, path: str) -> tuple[int, dict[str, Any]]:
        if path == "/v1/health":
            return 200, self.app.health()
        turn_route = self._turn_route(path)
        if turn_route is not None:
            session_id, turn_id = turn_route
            return 200, self.app.turns.get(
                session_id=session_id, token=self._bearer(), turn_id=turn_id
            )
        session_id = self._session_route(path)
        if session_id is None:
            raise BrainError("INVALID_ROUTE", 404, "route is unavailable")
        return 200, self.app.manager.status(session_id=session_id, token=self._bearer())

    def _dispatch_post(self, path: str) -> tuple[int, dict[str, Any]]:
        body = self._body()
        token = self._bearer()
        if path == "/v1/session-options":
            self.app.authenticate_bootstrap(token)
            exact_fields(body, required={"client_id"}, label="session options request")
            return 200, self.app.manager.session_options(
                client_id=bounded_identifier(body["client_id"], kind="client")
            )
        if path == "/v1/sessions":
            self.app.authenticate_bootstrap(token)
            exact_fields(
                body,
                required={"client_id", "tenant_alias", "capabilities"},
                label="open session request",
            )
            opened = self.app.manager.create_session(
                client_id=bounded_identifier(body["client_id"], kind="client"),
                tenant_alias=bounded_identifier(body["tenant_alias"], kind="tenant"),
                requested_capabilities=capability_set(body["capabilities"]),
            )
            return 201, opened.payload()

        turn_route = self._turn_route(path, "/apply-preflight")
        if turn_route is not None:
            session_id, turn_id = turn_route
            return 200, self.app.turns.apply_preflight(
                session_id=session_id, token=token, turn_id=turn_id, body=body
            )
        turn_route = self._turn_route(path, "/answer")
        if turn_route is not None:
            session_id, parent_turn_id = turn_route
            answer = ClarificationAnswerRequest.parse(body)
            record = self.app.turns.answer(
                session_id=session_id,
                token=token,
                parent_turn_id=parent_turn_id,
                answer=answer,
            )
            return 202, {
                "schema_version": record.request.schema_version,
                "turn_id": record.turn_id,
                "request_id": record.request.request_id,
                "status": record.status,
            }
        session_id = self._turn_collection_route(path)
        if session_id is not None:
            request = TurnRequest.parse(body)
            record = self.app.turns.submit(session_id=session_id, token=token, request=request)
            return 202, {
                "schema_version": request.schema_version,
                "turn_id": record.turn_id,
                "request_id": request.request_id,
                "status": record.status,
            }

        session_id = self._session_route(path, "/context")
        if session_id is not None:
            exact_fields(body, required={"expected_revision"}, label="context request")
            expected = revision(body["expected_revision"])
            with self.app.manager.operation(
                session_id=session_id,
                token=token,
                capability="context.read",
                expected_revision=expected,
            ) as lease:
                return 200, lease.snapshot.public_payload()

        session_id = self._session_route(path, "/compile")
        if session_id is not None:
            exact_fields(
                body,
                required={
                    "expected_revision",
                    "source",
                    "filename",
                    "execution_mode",
                    "endpoint",
                },
                label="compile request",
            )
            expected = revision(body["expected_revision"])
            source, filename, execution_mode, endpoint = validate_compile_request(
                source=body["source"],
                filename=body["filename"],
                execution_mode=body["execution_mode"],
                endpoint=body["endpoint"],
            )
            with self.app.manager.operation(
                session_id=session_id,
                token=token,
                capability="compile",
                expected_revision=expected,
            ) as lease:
                return 200, self.app.compiler.compile(
                    lease=lease,
                    source=source,
                    filename=filename,
                    execution_mode=execution_mode,
                    endpoint=endpoint,
                )
        raise BrainError("INVALID_ROUTE", 404, "route is unavailable")

    def _dispatch_delete(self, path: str) -> tuple[int, dict[str, Any]]:
        turn_route = self._turn_route(path)
        if turn_route is not None:
            session_id, turn_id = turn_route
            return 200, self.app.turns.cancel(
                session_id=session_id, token=self._bearer(), turn_id=turn_id
            )
        session_id = self._session_route(path)
        if session_id is None:
            raise BrainError("INVALID_ROUTE", 404, "route is unavailable")
        return 200, self.app.manager.close(session_id=session_id, token=self._bearer())

    def _dispatch_sse(self, path: str) -> None:
        turn_route = self._turn_route(path, "/events")
        if turn_route is None:
            raise BrainError("INVALID_ROUTE", 404, "route is unavailable")
        session_id, turn_id = turn_route
        last_header = self.headers.get("Last-Event-ID", "0")
        if not last_header.isascii() or not last_header.isdigit():
            raise BrainError("INVALID_SCHEMA", 400, "Last-Event-ID is invalid")
        record, events = self.app.turns.events(
            session_id=session_id,
            token=self._bearer(),
            turn_id=turn_id,
            last_event_id=int(last_header),
        )
        if record.terminal is None:
            with record.condition:
                record.condition.wait(timeout=30.0)
                events = [
                    item for item in record.events if item["data"]["sequence"] > int(last_header)
                ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        for item in events:
            sequence = item["data"]["sequence"]
            raw = canonical_json(item["data"])
            self.wfile.write(f"id: {sequence}\nevent: {item['event']}\ndata: ".encode())
            self.wfile.write(raw)
            self.wfile.write(b"\n\n")
        self.wfile.flush()
        self.close_connection = True

    def _handle(self, method: str) -> None:
        try:
            path = self._guard_transport()
            if method == "GET":
                self._require_no_body()
                if path.endswith("/events"):
                    self._dispatch_sse(path)
                    return
                status, payload = self._dispatch_get(path)
            elif method == "POST":
                status, payload = self._dispatch_post(path)
            elif method == "DELETE":
                self._require_no_body()
                status, payload = self._dispatch_delete(path)
            else:
                raise BrainError("METHOD_NOT_ALLOWED", 405, "method is not allowed")
            self._response(status, payload)
        except BrainError as error:
            self._response(error.status, error.payload())
        except Exception:
            self._response(
                500,
                BrainError("INTERNAL_ERROR", 500, "internal service error").payload(),
            )

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._handle("POST")

    def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._handle("DELETE")

    def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._handle("PUT")

    def do_PATCH(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._handle("PATCH")

    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._handle("OPTIONS")

    def do_TRACE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._handle("TRACE")

    def do_CONNECT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._handle("CONNECT")

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        try:
            self._guard_transport()
            payload = BrainError("METHOD_NOT_ALLOWED", 405, "method is not allowed").payload()
            self._response(405, payload, write_body=False)
        except BrainError as error:
            self._response(error.status, error.payload(), write_body=False)


class MetisBrainService:
    """Lifecycle wrapper used by the CLI and live tests."""

    def __init__(
        self,
        config: BrainConfig,
        *,
        compiler: BrainCompiler | None = None,
        retriever: Any | None = None,
        model: Any | None = None,
        intent_compiler: Any | None = None,
    ) -> None:
        if config.host != "127.0.0.1":
            raise BrainError("INVALID_CONFIG", 500, "service host must be numeric loopback")
        if config.model is not None and (config.retrieval is None or not config.retrieval.schema2):
            raise BrainError(
                "INVALID_CONFIG", 500, "model configuration requires schema2 retrieval"
            )
        if config.model is not None and config.model.warmup not in MODEL_WARMUP_POLICIES:
            raise BrainError("INVALID_CONFIG", 500, "model warmup policy is invalid")
        if config.intent_compiler is not None and (
            config.retrieval is None or not config.retrieval.schema2
        ):
            raise BrainError(
                "INVALID_CONFIG", 500, "intent compiler configuration requires schema2 retrieval"
            )
        self.runtime = BrainRuntime(config.runtime_root)
        manager: SessionManager | None = None
        httpd: _ThreadingBrainHTTPServer | None = None
        model_runtime = model
        intent_runtime = intent_compiler
        try:
            if compiler is None:
                compiler = BrainCompiler(
                    metis_root=config.metis_git_root,
                    node_path=config.node_path,
                    max_concurrency=config.compiler_concurrency,
                )
            if retriever is None:
                if config.retrieval is not None and config.retrieval.schema2:
                    loader_options: dict[str, Any] = {
                        "metis_root": config.metis_git_root,
                        "node_path": config.node_path,
                        "max_concurrency": config.compiler_concurrency,
                    }
                    if isinstance(compiler, BrainCompiler):
                        loader_options["authority"] = compiler.authority
                    loader = PinnedCatalogProjectionLoader(
                        **loader_options,
                    )
                    retriever = Schema2SnapshotRetriever(loader)
                else:
                    retriever = SnapshotRetriever()
            if model_runtime is None and config.model is not None:
                model_runtime = MlxBrainModelRuntime(
                    python_path=config.model.python_path,
                    model_path=config.model.model_path,
                    adapter_path=config.model.adapter_path,
                    timeout_seconds=config.model.timeout_seconds,
                )
            if config.model is not None and config.model.warmup == "on_start":
                warmup = getattr(model_runtime, "warmup", None)
                if not callable(warmup):
                    raise BrainError(
                        "MODEL_RUNTIME_CONFIG", 500, "configured model cannot be warmed"
                    )
                warmup_receipt = warmup()
                if (
                    not isinstance(warmup_receipt, dict)
                    or set(warmup_receipt) != {"status", "duration_ms", "worker_load_ms"}
                    or warmup_receipt.get("status") != "ready"
                    or any(
                        type(warmup_receipt.get(key)) is not int
                        or not 0 <= warmup_receipt[key] <= MAX_TELEMETRY_COUNT
                        for key in ("duration_ms", "worker_load_ms")
                    )
                    or getattr(model_runtime, "model_loaded", None) is not True
                    or getattr(model_runtime, "prefix_cache_ready", None) is not True
                    or type(getattr(model_runtime, "warmup_prefix_tokens", None)) is not int
                    or not 1
                    <= getattr(model_runtime, "warmup_prefix_tokens", 0)
                    <= MAX_PREFIX_CACHE_TOKENS
                ):
                    raise BrainError(
                        "MODEL_RUNTIME_CONFIG", 500, "configured model warmup did not complete"
                    )
            if intent_runtime is None and config.intent_compiler is not None:
                intent_runtime = MlxFlashIntentRuntime(
                    python_path=config.intent_compiler.python_path,
                    model_path=config.intent_compiler.model_path,
                    timeout_seconds=config.intent_compiler.timeout_seconds,
                )
            if config.intent_compiler is not None:
                warmup = getattr(intent_runtime, "warmup", None)
                if not callable(warmup):
                    raise BrainError(
                        "FLASH_RUNTIME_CONFIG", 500, "configured intent compiler cannot be warmed"
                    )
                warmup_receipt = warmup()
                if (
                    not isinstance(warmup_receipt, dict)
                    or set(warmup_receipt) != {"status", "duration_ms", "worker_load_ms"}
                    or warmup_receipt.get("status") != "ready"
                    or any(
                        type(warmup_receipt.get(key)) is not int
                        or not 0 <= warmup_receipt[key] <= MAX_TELEMETRY_COUNT
                        for key in ("duration_ms", "worker_load_ms")
                    )
                    or getattr(intent_runtime, "model_loaded", None) is not True
                ):
                    raise BrainError(
                        "FLASH_RUNTIME_CONFIG",
                        500,
                        "configured intent compiler warmup did not complete",
                    )
            registry = TenantRegistry(list(config.tenant_grants))
            manager = SessionManager(
                registry=registry,
                policies=list(config.client_policies),
                runtime_root=self.runtime.run_dir / "sessions",
                toolchain_binding=compiler.toolchain_binding,
                limits=config.limits,
            )
            self.app = BrainApplication(
                runtime=self.runtime,
                manager=manager,
                compiler=compiler,
                retriever=retriever,
                model=model_runtime,
                model_warmup_policy=config.model.warmup if config.model is not None else "disabled",
                intent_compiler=intent_runtime,
            )
            httpd = _ThreadingBrainHTTPServer((config.host, config.port), self.app)
            self.httpd = httpd
            bound_host, _bound_port = httpd.server_address
            if bound_host != "127.0.0.1":
                raise BrainError("BIND_FAILED", 500, "service did not bind numeric loopback")
        except BaseException:
            if httpd is not None:
                httpd.server_close()
            if manager is not None:
                manager.shutdown()
            if model_runtime is not None:
                close = getattr(model_runtime, "close", None)
                if callable(close):
                    close()
            if intent_runtime is not None:
                close = getattr(intent_runtime, "close", None)
                if callable(close):
                    close()
            if retriever is not None:
                close = getattr(retriever, "close", None)
                if callable(close):
                    close()
            if compiler is not None:
                close = getattr(compiler, "close", None)
                if callable(close):
                    close()
            self.runtime.close()
            raise
        self._server_thread: threading.Thread | None = None
        self._reaper_stop = threading.Event()
        self._reaper_thread: threading.Thread | None = None
        self._serving = threading.Event()
        self._close_lock = threading.Lock()
        self._close_done = threading.Event()

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.httpd.server_address
        return str(host), int(port)

    def _reap(self) -> None:
        while not self._reaper_stop.wait(5.0):
            self.app.manager.sweep_expired()

    def start_background(self) -> None:
        if self._server_thread is not None:
            raise BrainError("SERVICE_STATE", 500, "service is already running")

        def serve() -> None:
            self._serving.set()
            try:
                self.httpd.serve_forever()
            finally:
                self._serving.clear()

        self._server_thread = threading.Thread(
            target=serve,
            name="metis-brain-http",
            daemon=True,
        )
        self._reaper_thread = threading.Thread(
            target=self._reap,
            name="metis-brain-reaper",
            daemon=True,
        )
        self._server_thread.start()
        self._reaper_thread.start()
        if not self._serving.wait(timeout=5):
            self.close()
            raise BrainError("SERVICE_STATE", 500, "service did not start")

    def serve_forever(self) -> None:
        self._reaper_thread = threading.Thread(
            target=self._reap,
            name="metis-brain-reaper",
            daemon=True,
        )
        self._reaper_thread.start()
        self._serving.set()
        try:
            self.httpd.serve_forever()
        finally:
            self._serving.clear()

    def close(self) -> None:
        if self._close_done.is_set():
            return
        with self._close_lock:
            if self._close_done.is_set():
                return
            try:
                self._reaper_stop.set()
                if self._serving.is_set():
                    self.httpd.shutdown()
                self.httpd.server_close()
                self.app.close()
                self.app.manager.shutdown()
                if (
                    self._server_thread is not None
                    and self._server_thread is not threading.current_thread()
                ):
                    self._server_thread.join(timeout=5)
                if (
                    self._reaper_thread is not None
                    and self._reaper_thread is not threading.current_thread()
                ):
                    self._reaper_thread.join(timeout=5)
            finally:
                self.runtime.close()
                self._close_done.set()

    def __enter__(self) -> MetisBrainService:
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()


def run_brain_server(config_path: Path) -> int:
    service: MetisBrainService | None = None
    previous_handlers: dict[int, Any] = {}

    def stop(_signum: int, _frame: Any) -> None:
        if service is None:
            # Interrupt construction on the main thread. MetisBrainService's
            # BaseException guard then removes any partial runtime/token.
            raise KeyboardInterrupt
        threading.Thread(target=service.close, daemon=True).start()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, stop)
    try:
        config = load_brain_config(config_path)
        service = MetisBrainService(config)
        ready = {
            "schema_version": 1,
            "status": "ready",
            "service": "metis-brain",
            "address": {"host": service.address[0], "port": service.address[1]},
            "bootstrap_file": str(service.runtime.bootstrap_file),
        }
        print(json.dumps(ready, sort_keys=True), flush=True)
        service.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if service is not None:
            service.close()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return 0
