"""Authenticated numeric-loopback HTTP service for Metis Brain."""

from __future__ import annotations

import hashlib
import hmac
import http.server
import json
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
from metis_model1.brain_sessions import ClientPolicy, SessionLimits, SessionManager
from metis_model1.brain_tools import BrainCompiler, validate_compile_request

MAX_CONFIG_BYTES = 1024 * 1024
MAX_HTTP_WORKERS = 64
REQUEST_SOCKET_TIMEOUT_SECONDS = 15.0


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


def _config_path(value: Any, *, label: str, may_create: bool = False) -> Path:
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
    if resolved != path:
        raise BrainError("INVALID_CONFIG", 500, f"{label} must be canonical")
    return resolved


def load_brain_config(path: Path) -> BrainConfig:
    value = parse_json_object(_safe_config_bytes(Path(path)), label="config")
    exact_fields(
        value,
        required={"schema_version", "server", "toolchain", "tenants", "clients", "limits"},
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
        self.run_dir.mkdir(mode=0o700)
        self.bootstrap_file = self.run_dir / "bootstrap.token"
        token = secrets.token_urlsafe(32)
        descriptor = os.open(
            self.bootstrap_file,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            os.write(descriptor, (token + "\n").encode("ascii"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(self.bootstrap_file, 0o600)
        self.bootstrap_digest = hashlib.sha256(token.encode("ascii")).digest()
        token = ""
        self._closed = False

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
    ) -> None:
        self.runtime = runtime
        self.manager = manager
        self.compiler = compiler

    def authenticate_bootstrap(self, token: str) -> None:
        if not self.runtime.authenticate(token):
            raise BrainError("BOOTSTRAP_UNAUTHORIZED", 401, "bootstrap authorization failed")

    def health(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "ready",
            "service": "metis-brain",
            "protocol": "v1",
            "compiler_configured": True,
            "compiler_executions": getattr(self.compiler, "execution_count", 0),
            "model_loaded": False,
            "metrics": self.manager.aggregate_metrics(),
        }


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

    def _dispatch_get(self, path: str) -> tuple[int, dict[str, Any]]:
        if path == "/v1/health":
            return 200, self.app.health()
        session_id = self._session_route(path)
        if session_id is None:
            raise BrainError("INVALID_ROUTE", 404, "route is unavailable")
        return 200, self.app.manager.status(session_id=session_id, token=self._bearer())

    def _dispatch_post(self, path: str) -> tuple[int, dict[str, Any]]:
        body = self._body()
        token = self._bearer()
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
        session_id = self._session_route(path)
        if session_id is None:
            raise BrainError("INVALID_ROUTE", 404, "route is unavailable")
        return 200, self.app.manager.close(session_id=session_id, token=self._bearer())

    def _handle(self, method: str) -> None:
        try:
            path = self._guard_transport()
            if method == "GET":
                self._require_no_body()
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

    def __init__(self, config: BrainConfig) -> None:
        if config.host != "127.0.0.1":
            raise BrainError("INVALID_CONFIG", 500, "service host must be numeric loopback")
        self.runtime = BrainRuntime(config.runtime_root)
        manager: SessionManager | None = None
        httpd: _ThreadingBrainHTTPServer | None = None
        try:
            compiler = BrainCompiler(
                metis_root=config.metis_git_root,
                node_path=config.node_path,
                max_concurrency=config.compiler_concurrency,
            )
            registry = TenantRegistry(list(config.tenant_grants))
            manager = SessionManager(
                registry=registry,
                policies=list(config.client_policies),
                runtime_root=self.runtime.run_dir / "sessions",
                toolchain_binding=compiler.toolchain_binding,
                limits=config.limits,
            )
            self.app = BrainApplication(runtime=self.runtime, manager=manager, compiler=compiler)
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
    previous_handlers: dict[int, Any] = {}

    def stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=service.close, daemon=True).start()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, stop)
    try:
        service.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.close()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return 0
