#!/usr/bin/env python3
"""FD3 broker service and fixed transport to the privileged launcher.

This L70 module is locally testable but performs no installation, privilege
change, key generation, Node/Metis execution or production authorization.
The client-facing envelope is intentionally distinct from the launcher frame:
the broker nonce does not exist until the durable core consumes the request.
"""

from __future__ import annotations

import hashlib
import socket
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from runtime import w3_broker_protocol as protocol

BROKER_LISTENER_FD = 3
LAUNCHER_SOCKET_PATH = "/var/run/metis-model1/w3-launcher.sock"
BROKER_SOCKET_PATH = "/var/run/metis-model1/w3-broker.sock"
INSTALLED_CONFIG_PATH = Path(
    "/Library/Application Support/MetisModel1/broker/config/w3-broker-config.json"
)
CALLER_UID = 501
CALLER_GID = 20
SERVICE_HEADER_BYTES = 4
MAX_SERVICE_BYTES = protocol.MAX_PAYLOAD_BYTES
MAX_LAUNCHER_RESPONSE_BYTES = protocol.RESPONSE_HEADER_BYTES + protocol.MAX_PAYLOAD_BYTES
SERVICE_IO_TIMEOUT_SECONDS = 5.0
LAUNCHER_IO_TIMEOUT_SECONDS = 130.0

NATIVE_RESULT_MAGIC = b"M1W3RES\x00"
NATIVE_CLEANUP_MAGIC = b"M1W3CLN\x00"
NATIVE_RESULT_VERSION = 1
NATIVE_RESULT_HEADER_BYTES = 36
NATIVE_CLEANUP_BYTES = 72
NATIVE_MAX_STDOUT_BYTES = 3 * 1024 * 1024
NATIVE_MAX_STDERR_BYTES = 1024 * 1024 - 4096

FLAG_EXITED = 1 << 0
FLAG_SIGNALED = 1 << 1
FLAG_TIMED_OUT = 1 << 2
FLAG_OUTPUT_CAPPED = 1 << 3
FLAG_PROCESS_GROUP_ZERO = 1 << 4
FLAG_FD_ZERO = 1 << 5
FLAG_TEMP_ZERO = 1 << 6
KNOWN_RESULT_FLAGS = (
    FLAG_EXITED
    | FLAG_SIGNALED
    | FLAG_TIMED_OUT
    | FLAG_OUTPUT_CAPPED
    | FLAG_PROCESS_GROUP_ZERO
    | FLAG_FD_ZERO
    | FLAG_TEMP_ZERO
)
REQUIRED_CLEANUP_FLAGS = FLAG_PROCESS_GROUP_ZERO | FLAG_FD_ZERO | FLAG_TEMP_ZERO

WAIT_UNAVAILABLE = 0
WAIT_EXITED = 1
WAIT_SIGNALED = 2

# Darwin exposes peer credentials for AF_UNIX sockets as ``struct xucred``
# through getsockopt(SOL_LOCAL, LOCAL_PEERCRED).  CPython on macOS does not
# expose getpeereid(), and SO_ACCEPTCONN is not available for AF_UNIX sockets.
SOL_LOCAL = 0
XUCRED_VERSION = 0
XUCRED_FORMAT = "@IIh2x16I"
XUCRED_BYTES = struct.calcsize(XUCRED_FORMAT)


class BrokerServiceError(RuntimeError):
    """Typed local service/launcher failure with a stable code."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


class BrokerCore(Protocol):
    def handle(self, canonical_request: bytes) -> bytes: ...


@dataclass(frozen=True)
class NativeLauncherResult:
    flags: int
    wait_kind: int
    wait_value: int
    stdout: bytes
    stderr: bytes
    cleanup_record: bytes
    broker_peer_uid: int
    broker_peer_gid: int
    launcher_actual_uid: int
    launcher_actual_gid: int
    runner_target_uid: int
    runner_target_gid: int
    child_boundary_succeeded: bool


@dataclass(frozen=True)
class PreparedLauncherPayload:
    """Payload prepared and premeasured before the launcher can be contacted."""

    payload: bytes
    context: object


class LauncherPayloadAdapter(Protocol):
    def __call__(
        self,
        request: Mapping[str, object],
        authority: Mapping[str, object],
        attempt: Mapping[str, object],
    ) -> PreparedLauncherPayload: ...


class NativeResultAdapter(Protocol):
    """Trusted installed adapter from measured native bytes to core evidence."""

    def __call__(
        self,
        native: NativeLauncherResult,
        prepared: PreparedLauncherPayload,
        request: Mapping[str, object],
        authority: Mapping[str, object],
        attempt: Mapping[str, object],
    ) -> Mapping[str, object]: ...


class LauncherConnector(Protocol):
    def __call__(self, fixed_path: str) -> socket.socket: ...


def _sha256(payload: bytes) -> str:
    return protocol.SHA256_PREFIX + hashlib.sha256(payload).hexdigest()


def _recv_exact(connection: object, count: int, label: str) -> bytes:
    receive = getattr(connection, "recv", None)
    if not callable(receive):
        raise BrokerServiceError("SOCKET_UNREADABLE", label)
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = receive(remaining)
        if not chunk:
            raise BrokerServiceError("FRAME_TRUNCATED", label)
        raw = bytes(chunk)
        chunks.append(raw)
        remaining -= len(raw)
    return b"".join(chunks)


def encode_service_envelope(payload: bytes) -> bytes:
    if not isinstance(payload, bytes | bytearray):
        raise BrokerServiceError("FRAME_NOT_BYTES")
    body = bytes(payload)
    if not body:
        raise BrokerServiceError("FRAME_EMPTY")
    if len(body) > MAX_SERVICE_BYTES:
        raise BrokerServiceError("FRAME_OVERSIZE", str(len(body)))
    return struct.pack(">I", len(body)) + body


def read_service_envelope(connection: object) -> bytes:
    prefix = _recv_exact(connection, SERVICE_HEADER_BYTES, "service-prefix")
    length = struct.unpack(">I", prefix)[0]
    if length == 0:
        raise BrokerServiceError("FRAME_EMPTY")
    if length > MAX_SERVICE_BYTES:
        raise BrokerServiceError("FRAME_OVERSIZE", str(length))
    payload = _recv_exact(connection, length, "service-payload")
    receive = getattr(connection, "recv", None)
    trailing = receive(1) if callable(receive) else b""
    if trailing:
        raise BrokerServiceError("FRAME_TRAILING_BYTES")
    return payload


def handle_service_connection(connection: object, broker: BrokerCore) -> None:
    """Serve exactly one request; the peer must half-close after its envelope."""

    canonical_request = read_service_envelope(connection)
    try:
        parsed = protocol.parse_canonical_json(canonical_request)
        protocol.validate_request(parsed)
    except protocol.BrokerProtocolError as error:
        raise BrokerServiceError("REQUEST_INVALID", str(error)) from error
    response = broker.handle(canonical_request)
    if not isinstance(response, bytes | bytearray):
        raise BrokerServiceError("CORE_RESPONSE_INVALID")
    sendall = getattr(connection, "sendall", None)
    shutdown = getattr(connection, "shutdown", None)
    if not callable(sendall) or not callable(shutdown):
        raise BrokerServiceError("SOCKET_UNWRITABLE")
    sendall(encode_service_envelope(bytes(response)))
    shutdown(socket.SHUT_WR)


def _set_timeout(connection: object, seconds: float) -> None:
    settimeout = getattr(connection, "settimeout", None)
    if callable(settimeout):
        settimeout(seconds)


def serve_listener(
    listener: object,
    broker: BrokerCore,
    *,
    max_connections: int | None = None,
) -> None:
    """Serial bounded accept loop; per-connection failures never mutate the listener."""

    if max_connections is not None and (type(max_connections) is not int or max_connections < 1):
        raise BrokerServiceError("BAD_CONNECTION_BOUND")
    accept = getattr(listener, "accept", None)
    if not callable(accept):
        raise BrokerServiceError("LISTENER_INVALID")
    handled = 0
    while max_connections is None or handled < max_connections:
        connection, _peer = accept()
        try:
            _set_timeout(connection, SERVICE_IO_TIMEOUT_SECONDS)
            peer_uid, peer_gid = _peer_credentials(
                connection,
                unavailable_code="CALLER_PEER_CREDENTIALS_UNAVAILABLE",
            )
            if peer_uid != CALLER_UID or peer_gid != CALLER_GID:
                raise BrokerServiceError("CALLER_PEER_NOT_AUTHORIZED")
            handle_service_connection(connection, broker)
        except Exception:
            # Invalid frames fail closed for that connection. The launchd-owned
            # listener remains available for later independent requests.
            pass
        finally:
            connection.close()
        handled += 1


def serve_inherited_fd3(broker: BrokerCore, *, max_connections: int | None = None) -> None:
    """Take ownership of exactly launchd/shim-supplied FD3; no pathname API exists."""

    listener = socket.socket(fileno=BROKER_LISTENER_FD)
    try:
        try:
            bound_path = listener.getsockname()
        except OSError as error:
            raise BrokerServiceError("LISTENER_INVALID", str(error)) from error
        if (
            listener.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
            or listener.family != socket.AF_UNIX
            or bound_path != BROKER_SOCKET_PATH
        ):
            raise BrokerServiceError("LISTENER_INVALID")
        serve_listener(listener, broker, max_connections=max_connections)
    finally:
        listener.close()


def _connect_fixed_launcher(path: str) -> socket.socket:
    if path != LAUNCHER_SOCKET_PATH:
        raise BrokerServiceError("LAUNCHER_PATH_NOT_FIXED")
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.connect(LAUNCHER_SOCKET_PATH)
    except BaseException:
        connection.close()
        raise
    return connection


def _peer_credentials(
    connection: object,
    *,
    unavailable_code: str,
) -> tuple[int, int]:
    getsockopt = getattr(connection, "getsockopt", None)
    if not callable(getsockopt):
        raise BrokerServiceError(unavailable_code)
    try:
        raw = getsockopt(SOL_LOCAL, socket.LOCAL_PEERCRED, XUCRED_BYTES)
        if not isinstance(raw, bytes | bytearray) or len(raw) != XUCRED_BYTES:
            raise BrokerServiceError(unavailable_code)
        version, uid, group_count, gid, *_groups = struct.unpack(XUCRED_FORMAT, bytes(raw))
    except (OSError, struct.error) as error:
        raise BrokerServiceError(unavailable_code, str(error)) from error
    if version != XUCRED_VERSION or group_count < 1:
        raise BrokerServiceError(unavailable_code)
    return uid, gid


def _verify_root_launcher_peer(connection: object) -> None:
    uid, gid = _peer_credentials(
        connection,
        unavailable_code="LAUNCHER_PEER_CREDENTIALS_UNAVAILABLE",
    )
    if uid != 0 or gid != 0:
        raise BrokerServiceError("LAUNCHER_PEER_NOT_ROOT")


def _recv_launcher_response(connection: object) -> bytes:
    receive = getattr(connection, "recv", None)
    if not callable(receive):
        raise BrokerServiceError("LAUNCHER_SOCKET_UNREADABLE")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = receive(min(65536, MAX_LAUNCHER_RESPONSE_BYTES + 1 - total))
        if not chunk:
            break
        raw = bytes(chunk)
        chunks.append(raw)
        total += len(raw)
        if total > MAX_LAUNCHER_RESPONSE_BYTES:
            raise BrokerServiceError("LAUNCHER_RESPONSE_OVERSIZE")
    return b"".join(chunks)


def decode_native_launcher_result(
    payload: bytes,
    *,
    cleanup_sha256: str,
) -> NativeLauncherResult:
    if len(payload) < NATIVE_RESULT_HEADER_BYTES + NATIVE_CLEANUP_BYTES:
        raise BrokerServiceError("NATIVE_RESULT_TRUNCATED")
    if payload[:8] != NATIVE_RESULT_MAGIC:
        raise BrokerServiceError("NATIVE_RESULT_MAGIC")
    version, flags, wait_kind, wait_value, stdout_len, stderr_len, cleanup_len = struct.unpack(
        ">7I", payload[8:NATIVE_RESULT_HEADER_BYTES]
    )
    if version != NATIVE_RESULT_VERSION:
        raise BrokerServiceError("NATIVE_RESULT_VERSION", str(version))
    if flags & ~KNOWN_RESULT_FLAGS:
        raise BrokerServiceError("NATIVE_RESULT_FLAGS")
    expected_size = NATIVE_RESULT_HEADER_BYTES + stdout_len + stderr_len + cleanup_len
    if expected_size != len(payload):
        raise BrokerServiceError("NATIVE_RESULT_LENGTH")
    if cleanup_len != NATIVE_CLEANUP_BYTES:
        raise BrokerServiceError("NATIVE_CLEANUP_LENGTH", str(cleanup_len))
    if stdout_len > NATIVE_MAX_STDOUT_BYTES or stderr_len > NATIVE_MAX_STDERR_BYTES:
        raise BrokerServiceError("NATIVE_OUTPUT_CAP")
    stdout_start = NATIVE_RESULT_HEADER_BYTES
    stderr_start = stdout_start + stdout_len
    cleanup_start = stderr_start + stderr_len
    stdout = payload[stdout_start:stderr_start]
    stderr = payload[stderr_start:cleanup_start]
    cleanup = payload[cleanup_start:]
    if _sha256(cleanup) != cleanup_sha256:
        raise BrokerServiceError("NATIVE_CLEANUP_DIGEST")
    if cleanup[:8] != NATIVE_CLEANUP_MAGIC:
        raise BrokerServiceError("NATIVE_CLEANUP_MAGIC")
    cleanup_values = struct.unpack(">16I", cleanup[8:])
    (
        cleanup_version,
        cleanup_flags,
        process_group_residual,
        retained_fds,
        temp_entries,
        cleanup_wait_kind,
        cleanup_wait_value,
        cleanup_stdout_len,
        cleanup_stderr_len,
        broker_peer_uid,
        broker_peer_gid,
        launcher_actual_uid,
        launcher_actual_gid,
        runner_target_uid,
        runner_target_gid,
        child_boundary_succeeded,
    ) = cleanup_values
    if cleanup_version != NATIVE_RESULT_VERSION:
        raise BrokerServiceError("NATIVE_CLEANUP_VERSION")
    if (
        cleanup_flags != flags
        or cleanup_wait_kind != wait_kind
        or cleanup_wait_value != wait_value
        or cleanup_stdout_len != stdout_len
        or cleanup_stderr_len != stderr_len
    ):
        raise BrokerServiceError("NATIVE_CLEANUP_CROSS_BINDING")
    if flags & (FLAG_TIMED_OUT | FLAG_OUTPUT_CAPPED):
        raise BrokerServiceError("NATIVE_EXECUTION_INCOMPLETE")
    if flags & REQUIRED_CLEANUP_FLAGS != REQUIRED_CLEANUP_FLAGS:
        raise BrokerServiceError("NATIVE_CLEANUP_FLAGS")
    if process_group_residual or retained_fds or temp_entries:
        raise BrokerServiceError("NATIVE_CLEANUP_RESIDUAL")
    if child_boundary_succeeded != 1:
        raise BrokerServiceError("NATIVE_CHILD_BOUNDARY_UNPROVEN")
    terminal_flags = flags & (FLAG_EXITED | FLAG_SIGNALED)
    if terminal_flags not in (FLAG_EXITED, FLAG_SIGNALED):
        raise BrokerServiceError("NATIVE_WAIT_FLAGS")
    expected_wait_kind = WAIT_EXITED if terminal_flags == FLAG_EXITED else WAIT_SIGNALED
    if wait_kind != expected_wait_kind:
        raise BrokerServiceError("NATIVE_WAIT_KIND")
    if (wait_kind == WAIT_EXITED and wait_value > 255) or (
        wait_kind == WAIT_SIGNALED and not 1 <= wait_value <= 127
    ):
        raise BrokerServiceError("NATIVE_WAIT_VALUE")
    return NativeLauncherResult(
        flags=flags,
        wait_kind=wait_kind,
        wait_value=wait_value,
        stdout=stdout,
        stderr=stderr,
        cleanup_record=cleanup,
        broker_peer_uid=broker_peer_uid,
        broker_peer_gid=broker_peer_gid,
        launcher_actual_uid=launcher_actual_uid,
        launcher_actual_gid=launcher_actual_gid,
        runner_target_uid=runner_target_uid,
        runner_target_gid=runner_target_gid,
        child_boundary_succeeded=True,
    )


def _validate_adapter_native_binding(
    result: Mapping[str, object],
    native: NativeLauncherResult,
) -> None:
    output = result.get("output")
    cleanup = result.get("cleanup")
    if not isinstance(output, Mapping) or not isinstance(cleanup, Mapping):
        raise BrokerServiceError("RESULT_ADAPTER_NATIVE_BINDING")
    expected_exit = native.wait_value if native.wait_kind == WAIT_EXITED else -native.wait_value
    if (
        output.get("stdout_sha256") != _sha256(native.stdout)
        or output.get("stderr_sha256") != _sha256(native.stderr)
        or output.get("exit_code") != expected_exit
    ):
        raise BrokerServiceError("RESULT_ADAPTER_OUTPUT_MISMATCH")
    cleanup_sha256 = _sha256(native.cleanup_record)
    process = cleanup.get("process_census")
    descriptors = cleanup.get("fd_census")
    temp = cleanup.get("temp_census")
    if (
        not isinstance(process, Mapping)
        or process.get("residual_children") != 0
        or process.get("census_sha256") != cleanup_sha256
        or not isinstance(descriptors, Mapping)
        or descriptors.get("retained_fds") != 0
        or descriptors.get("census_sha256") != cleanup_sha256
        or not isinstance(temp, Mapping)
        or temp.get("entries") != []
        or temp.get("roster_sha256") != cleanup_sha256
    ):
        raise BrokerServiceError("RESULT_ADAPTER_CLEANUP_MISMATCH")
    effective_ids = result.get("effective_ids")
    if not isinstance(effective_ids, Mapping) or effective_ids != {
        "broker_uid": native.broker_peer_uid,
        "broker_gid": native.broker_peer_gid,
        "runner_uid": native.runner_target_uid,
        "runner_gid": native.runner_target_gid,
        "launcher_uid": native.launcher_actual_uid,
        "launcher_gid": native.launcher_actual_gid,
    }:
        raise BrokerServiceError("RESULT_ADAPTER_NATIVE_IDENTITY_MISMATCH")


class FixedLauncherTransport:
    """Core executor that can connect only to the installed launcher socket."""

    def __init__(
        self,
        *,
        payload_adapter: LauncherPayloadAdapter,
        result_adapter: NativeResultAdapter,
        connector: LauncherConnector | None = None,
    ):
        if not callable(payload_adapter):
            raise BrokerServiceError("PAYLOAD_ADAPTER_REQUIRED")
        if not callable(result_adapter):
            raise BrokerServiceError("RESULT_ADAPTER_REQUIRED")
        if connector is not None and not callable(connector):
            raise BrokerServiceError("LAUNCHER_CONNECTOR_INVALID")
        self._payload_adapter = payload_adapter
        self._result_adapter = result_adapter
        self._connector = connector or _connect_fixed_launcher

    def __call__(
        self,
        request: Mapping[str, object],
        authority: Mapping[str, object],
        attempt: Mapping[str, object],
    ) -> Mapping[str, object]:
        prepared = self._payload_adapter(request, authority, attempt)
        if not isinstance(prepared, PreparedLauncherPayload):
            raise BrokerServiceError("PAYLOAD_ADAPTER_INVALID")
        payload = prepared.payload
        if (
            not isinstance(payload, bytes)
            or not payload
            or len(payload) > protocol.MAX_PAYLOAD_BYTES
        ):
            raise BrokerServiceError("PAYLOAD_ADAPTER_INVALID")
        frame = protocol.encode_request_frame(
            payload,
            request_sha256=str(request["request_hash"]),
            authority_sha256=protocol.authority_hash(authority),
            release_sha256=str(authority["release_identity"]["ancestry_root_sha256"]),
            broker_nonce=str(attempt["broker_nonce"]),
        )
        connection = self._connector(LAUNCHER_SOCKET_PATH)
        try:
            _verify_root_launcher_peer(connection)
            _set_timeout(connection, LAUNCHER_IO_TIMEOUT_SECONDS)
            connection.sendall(frame)
            connection.shutdown(socket.SHUT_WR)
            encoded_response = _recv_launcher_response(connection)
        except OSError as error:
            raise BrokerServiceError("LAUNCHER_IO", str(error)) from error
        finally:
            connection.close()
        try:
            response = protocol.decode_response_frame(encoded_response)
        except protocol.BrokerProtocolError as error:
            raise BrokerServiceError("LAUNCHER_FRAME_INVALID", str(error)) from error
        if response.status != protocol.STATUS_OK:
            raise BrokerServiceError("LAUNCHER_STATUS", str(response.status))
        if response.request_sha256 != request["request_hash"]:
            raise BrokerServiceError("LAUNCHER_REQUEST_MISMATCH")
        if response.broker_nonce != attempt["broker_nonce"]:
            raise BrokerServiceError("LAUNCHER_NONCE_MISMATCH")
        native = decode_native_launcher_result(
            response.payload,
            cleanup_sha256=response.cleanup_sha256,
        )
        result = self._result_adapter(native, prepared, request, authority, attempt)
        if not isinstance(result, Mapping):
            raise BrokerServiceError("RESULT_ADAPTER_INVALID")
        _validate_adapter_native_binding(result, native)
        return result


def build_installed_broker(config_path: Path = INSTALLED_CONFIG_PATH) -> BrokerCore:
    """Load the fixed installed factory lazily; tests can import this module safely."""

    from runtime.w3_broker_executor import build_installed_broker as build

    return build(config_path)


def main() -> int:
    broker = build_installed_broker()
    serve_inherited_fd3(broker)
    return 0


__all__ = [
    "BROKER_LISTENER_FD",
    "BrokerServiceError",
    "CALLER_GID",
    "CALLER_UID",
    "FixedLauncherTransport",
    "LAUNCHER_SOCKET_PATH",
    "NativeLauncherResult",
    "PreparedLauncherPayload",
    "build_installed_broker",
    "decode_native_launcher_result",
    "encode_service_envelope",
    "handle_service_connection",
    "read_service_envelope",
    "serve_inherited_fd3",
    "serve_listener",
]


if __name__ == "__main__":  # pragma: no cover - installed entrypoint only
    raise SystemExit(main())
