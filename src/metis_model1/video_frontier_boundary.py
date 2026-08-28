"""Public-synthetic macOS process boundary for frontier egress evidence.

This module proves one deliberately narrow property: two local Python peers can
exchange a synthetic payload over an inherited anonymous socketpair while the
same peer processes are denied DNS and TCP by a deny-default Seatbelt profile.

It does not load or inspect a model, adapter, checkpoint, tenant source, live
service, credential, keychain, ``.env`` file, or private artifact.  Consequently
its receipt is not evidence for a real model/checkpoint or production frontier
execution.  Those nonclaims are part of the validated public receipt.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import json
import os
import re
import resource
import socket
import stat
import struct
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
GATE = "VIDEO_FRONTIER_EGRESS_SYNTHETIC_BOUNDARY_VALID"
EVIDENCE_SCOPE = "public_synthetic_process_boundary"
ROLES = ("runner", "model")
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
SOURCE_PATH = Path(__file__).resolve()
DNS_CANARY_HOST = "example.com"
DNS_CANARY_PORT = 443
TCP_CANARY_HOST = "127.0.0.1"
MAX_MESSAGE_BYTES = 64 * 1024
MAX_OPEN_FILES = 64
CHILD_TIMEOUT_SECONDS = 10.0
SYNTHETIC_SENTINEL_RE = re.compile(r"\APUBLIC-SYNTHETIC-[A-Za-z0-9_-]{16,64}\Z")
SHA256_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")

FIXED_CHILD_ENVIRONMENT = {
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_OFFLINE": "1",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONNOUSERSITE": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "TRANSFORMERS_OFFLINE": "1",
    # CoreFoundation injects this value at exec on macOS.  Supplying the exact
    # deterministic per-UID value keeps the observed environment allowlisted;
    # it is neither a path nor a credential.
    "__CF_USER_TEXT_ENCODING": f"0x{os.getuid():X}:0:0",
}

FORBIDDEN_ENVIRONMENT_KEYS = frozenset(
    {
        "ALL_PROXY",
        "AWS_ACCESS_KEY_ID",
        "AWS_PROFILE",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "CREDENTIALS",
        "GIT_ASKPASS",
        "HOME",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "OPENAI_API_KEY",
        "PASSWORD",
        "PYTHONHOME",
        "PYTHONPATH",
        "SSH_AUTH_SOCK",
        "TOKEN",
    }
)

NONCLAIMS = (
    "no_real_model_loaded",
    "no_adapter_loaded",
    "no_checkpoint_verified",
    "no_private_source_processed",
    "no_live_service_accessed",
    "no_frontier_ontology_generation",
    "no_production_frontier_egress_gate",
    "no_training_authority",
    "no_accuracy_or_promotion_claim",
)

_CHILD_FAILURE_CODES = {
    "child environment differs from the fixed allowlist": "ENV_ALLOWLIST",
    "child environment digest mismatch": "ENV_DIGEST",
    "child source digest mismatch": "SOURCE_DIGEST",
    "child executable digest mismatch": "EXECUTABLE_DIGEST",
    "open-file limit differs from the fixed bound": "NOFILE_LIMIT",
    "child descriptor roster mismatch": "FD_ROSTER",
    "child peer socket boundary mismatch": "PEER_SOCKET",
    "child control socket boundary mismatch": "CONTROL_SOCKET",
    "child resource boundary mismatch": "RESOURCE_BOUNDARY",
    "child egress canary was not denied": "EGRESS_CANARY",
    "runner received an invalid synthetic result": "RUNNER_RESULT",
    "model received an invalid synthetic request": "MODEL_REQUEST_FIELDS",
    "model synthetic request identity mismatch": "MODEL_REQUEST_IDENTITY",
    "model synthetic payload digest mismatch": "MODEL_PAYLOAD_DIGEST",
}

RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "gate",
        "status",
        "evidence_scope",
        "platform",
        "architecture",
        "boundary",
        "controls",
        "processes",
        "sentinel",
        "nonclaims",
        "receipt_sha256",
    }
)
BOUNDARY_KEYS = frozenset(
    {
        "sandbox",
        "policy_mode",
        "network_rule",
        "transport",
        "peer_count",
        "environment_keys",
        "environment_sha256",
        "policy_sha256",
        "source_sha256",
        "python_executable_sha256",
        "sandbox_exec_sha256",
        "limits",
    }
)
LIMIT_KEYS = frozenset({"core_bytes", "file_bytes", "open_files"})
CONTROL_KEYS = frozenset(
    {
        "positive_control_scope",
        "dns_positive_control",
        "tcp_positive_control",
        "dns_attempted",
        "dns_denied",
        "tcp_attempted",
        "tcp_denied",
        "total_attempted",
        "total_denied",
        "sandbox_network_successes",
        "unexpected_attempts",
        "listener_positive_control_connections",
        "listener_sandbox_connections",
    }
)
PROCESS_KEYS = frozenset(
    {
        "role",
        "pid",
        "policy_sha256",
        "environment_sha256",
        "source_sha256",
        "python_executable_sha256",
        "fd_roster_valid",
        "observed_fd_count",
        "core_limit_zero",
        "file_limit_zero",
        "open_file_limit",
        "peer_socket_valid",
        "control_socket_valid",
        "dns_canary",
        "tcp_canary",
        "work_channel",
        "payload_sha256",
    }
)
SENTINEL_KEYS = frozenset(
    {
        "kind",
        "input_sha256",
        "receipt_occurrences",
        "child_stdout_occurrences",
        "child_stderr_occurrences",
        "control_report_occurrences",
    }
)


class FrontierBoundaryError(RuntimeError):
    """Raised when the synthetic no-egress boundary cannot prove its contract."""


@dataclass(frozen=True)
class _FileIdentity:
    path: Path
    device: int
    inode: int
    mode: int
    links: int
    size: int
    mtime_ns: int
    ctime_ns: int
    sha256: str


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise FrontierBoundaryError("value is not canonical JSON") from error


def _canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _raw_hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise FrontierBoundaryError(f"{label} is not a sha256 digest")
    return value


def _measure_regular_file(path: Path, label: str) -> _FileIdentity:
    """Hash one regular file and bind its pre/open/post identity."""

    try:
        resolved = path.resolve(strict=True)
        before = resolved.lstat()
        descriptor = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as error:
        raise FrontierBoundaryError(f"{label} is unavailable") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise FrontierBoundaryError(f"{label} is not a single-link regular file")
        digest = hashlib.sha256()
        total = 0
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            total += len(block)
            digest.update(block)
        after = os.fstat(descriptor)
        path_after = resolved.lstat()
    finally:
        os.close(descriptor)

    def identity(value: os.stat_result) -> tuple[int, ...]:
        return (
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
        or identity(after) != identity(path_after)
        or total != opened.st_size
    ):
        raise FrontierBoundaryError(f"{label} changed while measured")
    return _FileIdentity(
        path=resolved,
        device=opened.st_dev,
        inode=opened.st_ino,
        mode=opened.st_mode,
        links=opened.st_nlink,
        size=opened.st_size,
        mtime_ns=opened.st_mtime_ns,
        ctime_ns=opened.st_ctime_ns,
        sha256="sha256:" + digest.hexdigest(),
    )


def _same_file_identity(left: _FileIdentity, right: _FileIdentity) -> bool:
    return left == right


def build_child_environment() -> dict[str, str]:
    """Return the complete child environment; no parent value is inherited."""

    environment = dict(FIXED_CHILD_ENVIRONMENT)
    _validate_child_environment(environment)
    return environment


def _validate_child_environment(environment: Mapping[str, str]) -> None:
    if dict(environment) != FIXED_CHILD_ENVIRONMENT:
        raise FrontierBoundaryError("child environment differs from the fixed allowlist")
    for key in environment:
        upper = key.upper()
        if (
            upper in FORBIDDEN_ENVIRONMENT_KEYS
            or upper.startswith("DYLD_")
            or "SECRET" in upper
            or "CREDENTIAL" in upper
            or upper.endswith("_TOKEN")
            or upper.endswith("_PASSWORD")
            or upper.endswith("_API_KEY")
            or upper.endswith("_PROXY")
        ):
            raise FrontierBoundaryError("forbidden key in child environment")


def _seatbelt_quote(value: str) -> str:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise FrontierBoundaryError("unsafe Seatbelt path")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _literal(path: Path | str) -> str:
    return f'(literal "{_seatbelt_quote(str(path))}")'


def _subpath(path: Path | str) -> str:
    return f'(subpath "{_seatbelt_quote(str(path))}")'


def _ancestor_literals(path: Path) -> list[str]:
    values: list[str] = []
    current = path
    while True:
        values.append(_literal(current))
        if current == current.parent:
            break
        current = current.parent
    return values


def build_sandbox_policy(
    *, source_path: Path | None = None, python_executable: Path | None = None
) -> str:
    """Build the exact deny-default Seatbelt profile used by both peers."""

    source = (source_path or SOURCE_PATH).resolve(strict=True)
    executable = (python_executable or Path(sys.executable)).resolve(strict=True)
    prefixes = {
        Path(sys.prefix).resolve(strict=True),
        Path(sys.base_prefix).resolve(strict=True),
        executable.parent,
    }
    read_rules = {
        _literal("/dev/null"),
        _literal("/dev/urandom"),
        _literal("/private/etc/hosts"),
        _literal("/private/etc/protocols"),
        _literal("/private/etc/resolv.conf"),
        _literal("/private/etc/services"),
        _literal(source),
        _literal(executable),
        _subpath("/System/Library"),
        _subpath("/private/var/db/dyld"),
        _subpath("/usr/lib"),
        _subpath("/usr/share/locale"),
    }
    for prefix in prefixes:
        read_rules.add(_subpath(prefix))
        read_rules.update(_ancestor_literals(prefix))
    read_rules.update(_ancestor_literals(source))
    rules = " ".join(sorted(read_rules))
    return (
        "(version 1) "
        "(deny default) "
        "(deny network*) "
        "(deny process-fork) "
        f"(allow process-exec {_literal(executable)}) "
        f"(allow file-read* {rules}) "
        "(allow sysctl-read) "
        "(allow mach-lookup)"
    )


def _limit_child() -> None:
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (MAX_OPEN_FILES, MAX_OPEN_FILES))


def _send_json(channel: socket.socket, value: Mapping[str, Any]) -> None:
    raw = _canonical_bytes(value)
    if not raw or len(raw) > MAX_MESSAGE_BYTES:
        raise FrontierBoundaryError("message size is outside the fixed bound")
    channel.sendall(struct.pack(">I", len(raw)) + raw)


def _recv_exact(channel: socket.socket, length: int) -> bytes:
    if length < 0 or length > MAX_MESSAGE_BYTES:
        raise FrontierBoundaryError("invalid framed message length")
    chunks = bytearray()
    while len(chunks) < length:
        block = channel.recv(length - len(chunks))
        if not block:
            raise FrontierBoundaryError("peer closed a framed message")
        chunks.extend(block)
    return bytes(chunks)


def _recv_json(channel: socket.socket, *, timeout: float) -> dict[str, Any]:
    channel.settimeout(timeout)
    try:
        header = _recv_exact(channel, 4)
        length = struct.unpack(">I", header)[0]
        if length == 0 or length > MAX_MESSAGE_BYTES:
            raise FrontierBoundaryError("invalid framed JSON size")
        raw = _recv_exact(channel, length)
    except (OSError, TimeoutError) as error:
        raise FrontierBoundaryError("bounded channel read failed") from error
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise FrontierBoundaryError("channel message is not strict JSON") from error
    if not isinstance(value, dict) or _canonical_bytes(value) != raw:
        raise FrontierBoundaryError("channel message is not a canonical object")
    return value


def _open_fd_roster() -> tuple[int, ...]:
    soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft != MAX_OPEN_FILES:
        raise FrontierBoundaryError("open-file limit differs from the fixed bound")
    result = []
    for descriptor in range(int(soft)):
        try:
            fcntl.fcntl(descriptor, fcntl.F_GETFD)
        except OSError as error:
            if error.errno != errno.EBADF:
                raise FrontierBoundaryError("cannot enumerate child descriptors") from error
        else:
            result.append(descriptor)
    return tuple(result)


def _socket_is_anonymous_stream(channel: socket.socket) -> bool:
    try:
        local = channel.getsockname()
        peer = channel.getpeername()
        try:
            accepting = channel.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)
        except OSError as error:
            # Darwin reports ENOPROTOOPT for SO_ACCEPTCONN on AF_UNIX
            # socketpair endpoints.  A connected anonymous peer below is not a
            # listener; no other getsockopt failure is accepted.
            if error.errno != errno.ENOPROTOOPT:
                raise
            accepting = 0
        return (
            channel.family == socket.AF_UNIX
            and channel.type & socket.SOCK_STREAM == socket.SOCK_STREAM
            and local in ("", b"")
            and peer in ("", b"")
            and accepting == 0
        )
    except OSError:
        return False


def _dns_canary() -> dict[str, Any]:
    try:
        addresses = socket.getaddrinfo(
            DNS_CANARY_HOST,
            DNS_CANARY_PORT,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as error:
        return {"status": "denied", "error_class": "gaierror", "errno": error.errno}
    except PermissionError as error:
        return {"status": "denied", "error_class": "PermissionError", "errno": error.errno}
    except OSError as error:
        return {"status": "unexpected_error", "error_class": "OSError", "errno": error.errno}
    return {
        "status": "succeeded",
        "error_class": None,
        "errno": None,
        "address_count": len(addresses),
    }


def _tcp_canary(port: int) -> dict[str, Any]:
    try:
        connection = socket.create_connection((TCP_CANARY_HOST, port), timeout=1.0)
    except PermissionError as error:
        return {"status": "denied", "error_class": "PermissionError", "errno": error.errno}
    except OSError as error:
        return {"status": "unexpected_error", "error_class": "OSError", "errno": error.errno}
    connection.close()
    return {"status": "succeeded", "error_class": None, "errno": None}


def _validate_child_request(value: Mapping[str, Any], role: str) -> dict[str, Any]:
    common = {
        "schema_version",
        "role",
        "channel_sha256",
        "expected_environment_sha256",
        "expected_policy_sha256",
        "expected_source_sha256",
        "expected_python_executable_sha256",
        "tcp_port",
    }
    expected = common | ({"synthetic_payload"} if role == "runner" else {"payload_sha256"})
    if set(value) != expected:
        raise FrontierBoundaryError("child request fields differ from the allowlist")
    if value.get("schema_version") != SCHEMA_VERSION or value.get("role") != role:
        raise FrontierBoundaryError("child request identity mismatch")
    for key in (
        "channel_sha256",
        "expected_environment_sha256",
        "expected_policy_sha256",
        "expected_source_sha256",
        "expected_python_executable_sha256",
    ):
        _require_sha256(value.get(key), f"child request {key}")
    port = value.get("tcp_port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise FrontierBoundaryError("child request TCP port is invalid")
    if role == "runner":
        payload = value.get("synthetic_payload")
        if not isinstance(payload, str) or SYNTHETIC_SENTINEL_RE.fullmatch(payload) is None:
            raise FrontierBoundaryError("runner payload is not public-synthetic")
    else:
        _require_sha256(value.get("payload_sha256"), "model payload_sha256")
    return dict(value)


def _child_report(
    *,
    role: str,
    peer: socket.socket,
    control: socket.socket,
    request: Mapping[str, Any],
    expected_fds: tuple[int, ...],
) -> dict[str, Any]:
    environment = dict(os.environ)
    _validate_child_environment(environment)
    if _canonical_hash(environment) != request["expected_environment_sha256"]:
        raise FrontierBoundaryError("child environment digest mismatch")

    source_identity = _measure_regular_file(SOURCE_PATH, "child source")
    executable_identity = _measure_regular_file(Path(sys.executable), "child executable")
    if source_identity.sha256 != request["expected_source_sha256"]:
        raise FrontierBoundaryError("child source digest mismatch")
    if executable_identity.sha256 != request["expected_python_executable_sha256"]:
        raise FrontierBoundaryError("child executable digest mismatch")

    roster = _open_fd_roster()
    core = resource.getrlimit(resource.RLIMIT_CORE)
    file_size = resource.getrlimit(resource.RLIMIT_FSIZE)
    open_files = resource.getrlimit(resource.RLIMIT_NOFILE)
    peer_valid = _socket_is_anonymous_stream(peer)
    control_valid = _socket_is_anonymous_stream(control)
    if roster != expected_fds:
        raise FrontierBoundaryError("child descriptor roster mismatch")
    if not peer_valid:
        raise FrontierBoundaryError("child peer socket boundary mismatch")
    if not control_valid:
        raise FrontierBoundaryError("child control socket boundary mismatch")
    if (
        core != (0, 0)
        or file_size != (0, 0)
        or open_files
        != (
            MAX_OPEN_FILES,
            MAX_OPEN_FILES,
        )
    ):
        raise FrontierBoundaryError("child resource boundary mismatch")

    dns = _dns_canary()
    tcp = _tcp_canary(request["tcp_port"])
    if dns.get("status") != "denied" or tcp != {
        "status": "denied",
        "error_class": "PermissionError",
        "errno": errno.EPERM,
    }:
        raise FrontierBoundaryError("child egress canary was not denied")

    if role == "runner":
        payload = request["synthetic_payload"]
        payload_sha256 = _raw_hash(payload.encode("utf-8"))
        _send_json(
            peer,
            {
                "schema_version": SCHEMA_VERSION,
                "kind": "public_synthetic_work",
                "channel_sha256": request["channel_sha256"],
                "payload": payload,
            },
        )
        response = _recv_json(peer, timeout=CHILD_TIMEOUT_SECONDS)
        if set(response) != {
            "schema_version",
            "kind",
            "channel_sha256",
            "payload_sha256",
        } or response != {
            "schema_version": SCHEMA_VERSION,
            "kind": "public_synthetic_result",
            "channel_sha256": request["channel_sha256"],
            "payload_sha256": payload_sha256,
        }:
            raise FrontierBoundaryError("runner received an invalid synthetic result")
    else:
        work = _recv_json(peer, timeout=CHILD_TIMEOUT_SECONDS)
        if set(work) != {
            "schema_version",
            "kind",
            "channel_sha256",
            "payload",
        }:
            raise FrontierBoundaryError("model received an invalid synthetic request")
        payload = work.get("payload")
        if (
            work.get("schema_version") != SCHEMA_VERSION
            or work.get("kind") != "public_synthetic_work"
            or work.get("channel_sha256") != request["channel_sha256"]
            or not isinstance(payload, str)
            or SYNTHETIC_SENTINEL_RE.fullmatch(payload) is None
        ):
            raise FrontierBoundaryError("model synthetic request identity mismatch")
        payload_sha256 = _raw_hash(payload.encode("utf-8"))
        if payload_sha256 != request["payload_sha256"]:
            raise FrontierBoundaryError("model synthetic payload digest mismatch")
        _send_json(
            peer,
            {
                "schema_version": SCHEMA_VERSION,
                "kind": "public_synthetic_result",
                "channel_sha256": request["channel_sha256"],
                "payload_sha256": payload_sha256,
            },
        )

    return {
        "role": role,
        "pid": os.getpid(),
        "policy_sha256": request["expected_policy_sha256"],
        "environment_sha256": _canonical_hash(environment),
        "source_sha256": source_identity.sha256,
        "python_executable_sha256": executable_identity.sha256,
        "fd_roster_valid": True,
        "observed_fd_count": len(roster),
        "core_limit_zero": True,
        "file_limit_zero": True,
        "open_file_limit": MAX_OPEN_FILES,
        "peer_socket_valid": True,
        "control_socket_valid": True,
        "dns_canary": dns,
        "tcp_canary": tcp,
        "work_channel": "valid",
        "payload_sha256": payload_sha256,
    }


def _parse_child_argv(argv: Sequence[str]) -> tuple[str, int, int]:
    if len(argv) != 5 or argv[1] != "--isolated-child" or argv[2] not in ROLES:
        raise FrontierBoundaryError("invalid isolated-child invocation")
    try:
        peer_fd = int(argv[3], 10)
        control_fd = int(argv[4], 10)
    except ValueError as error:
        raise FrontierBoundaryError("invalid isolated-child descriptor") from error
    if (
        peer_fd in {0, 1, 2}
        or control_fd in {0, 1, 2}
        or peer_fd == control_fd
        or not 3 <= peer_fd < MAX_OPEN_FILES
        or not 3 <= control_fd < MAX_OPEN_FILES
    ):
        raise FrontierBoundaryError("isolated-child descriptors are outside the boundary")
    return argv[2], peer_fd, control_fd


def _isolated_child_main(argv: Sequence[str]) -> int:
    control: socket.socket | None = None
    try:
        role, peer_fd, control_fd = _parse_child_argv(argv)
        peer = socket.socket(fileno=peer_fd)
        control = socket.socket(fileno=control_fd)
        request = _validate_child_request(_recv_json(control, timeout=CHILD_TIMEOUT_SECONDS), role)
        expected_fds = tuple(sorted((0, 1, 2, peer_fd, control_fd)))
        report = _child_report(
            role=role,
            peer=peer,
            control=control,
            request=request,
            expected_fds=expected_fds,
        )
        _send_json(control, report)
        peer.close()
        control.close()
        return 0
    except Exception as error:  # fail closed without printing raw child state
        if control is not None:
            with contextlib.suppress(Exception):
                _send_json(
                    control,
                    {
                        "status": "invalid",
                        "failure_code": _CHILD_FAILURE_CODES.get(str(error), "BOUNDARY_INVALID"),
                    },
                )
        return 73


def _positive_controls(listener: socket.socket) -> tuple[int, int]:
    try:
        dns_addresses = socket.getaddrinfo(
            DNS_CANARY_HOST,
            DNS_CANARY_PORT,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except OSError as error:
        raise FrontierBoundaryError("external DNS positive control failed") from error
    if not dns_addresses:
        raise FrontierBoundaryError("external DNS positive control returned no addresses")

    port = listener.getsockname()[1]
    try:
        with socket.create_connection((TCP_CANARY_HOST, port), timeout=1.0) as connection:
            connection.sendall(b"P")
        accepted, _address = listener.accept()
        with accepted:
            accepted.settimeout(1.0)
            if accepted.recv(2) != b"P":
                raise FrontierBoundaryError("external TCP positive control payload mismatch")
    except OSError as error:
        raise FrontierBoundaryError("external TCP positive control failed") from error
    return len(dns_addresses), 1


def _count_listener_connections(listener: socket.socket) -> int:
    listener.setblocking(False)
    count = 0
    while True:
        try:
            accepted, _address = listener.accept()
        except BlockingIOError:
            return count
        with accepted:
            count += 1


def _terminate(processes: Sequence[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.kill()
    for process in processes:
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2.0)


def _validate_child_report(
    value: Mapping[str, Any],
    *,
    role: str,
    identities: Mapping[str, _FileIdentity],
    environment_sha256: str,
    policy_sha256: str,
    payload_sha256: str,
) -> dict[str, Any]:
    if set(value) == {"status", "failure_code"} and value.get("status") == "invalid":
        code = value.get("failure_code")
        if isinstance(code, str) and re.fullmatch(r"[A-Z_]{3,32}", code):
            raise FrontierBoundaryError(f"isolated child failed closed: {code}")
    if set(value) != PROCESS_KEYS or value.get("role") != role:
        raise FrontierBoundaryError("child report fields or role mismatch")
    if (
        not isinstance(value.get("pid"), int)
        or isinstance(value.get("pid"), bool)
        or value["pid"] <= 1
        or value.get("policy_sha256") != policy_sha256
        or value.get("environment_sha256") != environment_sha256
        or value.get("source_sha256") != identities["source"].sha256
        or value.get("python_executable_sha256") != identities["python"].sha256
        or value.get("payload_sha256") != payload_sha256
        or value.get("fd_roster_valid") is not True
        or value.get("observed_fd_count") != 5
        or value.get("core_limit_zero") is not True
        or value.get("file_limit_zero") is not True
        or value.get("open_file_limit") != MAX_OPEN_FILES
        or value.get("peer_socket_valid") is not True
        or value.get("control_socket_valid") is not True
        or value.get("work_channel") != "valid"
        or not isinstance(value.get("dns_canary"), dict)
        or value["dns_canary"].get("status") != "denied"
        or value.get("tcp_canary")
        != {"status": "denied", "error_class": "PermissionError", "errno": errno.EPERM}
    ):
        raise FrontierBoundaryError("child report did not prove the fixed boundary")
    return dict(value)


def _default_synthetic_sentinel() -> str:
    return "PUBLIC-SYNTHETIC-" + os.urandom(16).hex()


def _validate_sentinel(sentinel: str) -> None:
    if SYNTHETIC_SENTINEL_RE.fullmatch(sentinel) is None:
        raise FrontierBoundaryError("sentinel must be explicitly public-synthetic")


def run_synthetic_frontier_egress_boundary(*, sentinel: str | None = None) -> dict[str, Any]:
    """Run the bounded public-synthetic macOS proof and return its receipt."""

    if sys.platform != "darwin":
        raise FrontierBoundaryError("the synthetic Seatbelt boundary requires macOS")
    selected_sentinel = sentinel or _default_synthetic_sentinel()
    _validate_sentinel(selected_sentinel)

    identities = {
        "source": _measure_regular_file(SOURCE_PATH, "boundary source"),
        "python": _measure_regular_file(Path(sys.executable), "Python executable"),
        "sandbox": _measure_regular_file(SANDBOX_EXEC, "sandbox-exec"),
    }
    environment = build_child_environment()
    environment_sha256 = _canonical_hash(environment)
    policy = build_sandbox_policy(
        source_path=identities["source"].path,
        python_executable=identities["python"].path,
    )
    if "(deny default)" not in policy or "(deny network*)" not in policy:
        raise FrontierBoundaryError("Seatbelt profile is not deny-default/no-network")
    if "(allow default)" in policy:
        raise FrontierBoundaryError("Seatbelt profile contains allow-default")
    policy_sha256 = _raw_hash(policy.encode("utf-8"))
    payload_sha256 = _raw_hash(selected_sentinel.encode("utf-8"))
    channel_sha256 = _raw_hash(os.urandom(32))

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    listener.bind((TCP_CANARY_HOST, 0))
    listener.listen(8)
    listener.settimeout(1.0)
    _dns_address_count, positive_connections = _positive_controls(listener)
    port = listener.getsockname()[1]

    runner_peer, model_peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    runner_control_parent, runner_control_child = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    model_control_parent, model_control_child = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    child_sockets = (runner_peer, model_peer, runner_control_child, model_control_child)
    if any(channel.fileno() >= MAX_OPEN_FILES for channel in child_sockets):
        for channel in (
            runner_peer,
            model_peer,
            runner_control_parent,
            runner_control_child,
            model_control_parent,
            model_control_child,
            listener,
        ):
            channel.close()
        raise FrontierBoundaryError("inherited descriptor exceeds the fixed child bound")

    processes: list[subprocess.Popen[bytes]] = []
    reports: list[dict[str, Any]] = []
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    try:
        peers = (
            ("runner", runner_peer, runner_control_child),
            ("model", model_peer, model_control_child),
        )
        for role, peer, control in peers:
            command = [
                str(identities["sandbox"].path),
                "-p",
                policy,
                str(identities["python"].path),
                "-I",
                str(identities["source"].path),
                "--isolated-child",
                role,
                str(peer.fileno()),
                str(control.fileno()),
            ]
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                pass_fds=(peer.fileno(), control.fileno()),
                env=environment,
                preexec_fn=_limit_child,
                start_new_session=True,
            )
            processes.append(process)

        runner_peer.close()
        model_peer.close()
        runner_control_child.close()
        model_control_child.close()

        common_request = {
            "schema_version": SCHEMA_VERSION,
            "channel_sha256": channel_sha256,
            "expected_environment_sha256": environment_sha256,
            "expected_policy_sha256": policy_sha256,
            "expected_source_sha256": identities["source"].sha256,
            "expected_python_executable_sha256": identities["python"].sha256,
            "tcp_port": port,
        }
        _send_json(
            runner_control_parent,
            {**common_request, "role": "runner", "synthetic_payload": selected_sentinel},
        )
        _send_json(
            model_control_parent,
            {**common_request, "role": "model", "payload_sha256": payload_sha256},
        )

        raw_reports = (
            _recv_json(runner_control_parent, timeout=CHILD_TIMEOUT_SECONDS),
            _recv_json(model_control_parent, timeout=CHILD_TIMEOUT_SECONDS),
        )
        for role, raw_report in zip(ROLES, raw_reports, strict=True):
            reports.append(
                _validate_child_report(
                    raw_report,
                    role=role,
                    identities=identities,
                    environment_sha256=environment_sha256,
                    policy_sha256=policy_sha256,
                    payload_sha256=payload_sha256,
                )
            )

        for process in processes:
            try:
                stdout, stderr = process.communicate(timeout=CHILD_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as error:
                raise FrontierBoundaryError("isolated child exceeded its deadline") from error
            stdout_chunks.append(stdout)
            stderr_chunks.append(stderr)
            if process.returncode != 0:
                raise FrontierBoundaryError("isolated child exited invalid")
        if any(stdout_chunks) or any(stderr_chunks):
            raise FrontierBoundaryError("isolated child emitted a public log channel")
        if reports[0]["pid"] == reports[1]["pid"]:
            raise FrontierBoundaryError("runner and model must be distinct processes")

        sandbox_connections = _count_listener_connections(listener)
        if positive_connections != 1 or sandbox_connections != 0:
            raise FrontierBoundaryError("TCP listener observed an unexpected connection")

        post_identities = {
            "source": _measure_regular_file(SOURCE_PATH, "boundary source postflight"),
            "python": _measure_regular_file(Path(sys.executable), "Python executable postflight"),
            "sandbox": _measure_regular_file(SANDBOX_EXEC, "sandbox-exec postflight"),
        }
        if any(
            not _same_file_identity(identities[label], post_identities[label])
            for label in identities
        ):
            raise FrontierBoundaryError("an executed boundary file changed during the run")

        receipt_body: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "gate": GATE,
            "status": "VALID",
            "evidence_scope": EVIDENCE_SCOPE,
            "platform": "darwin",
            "architecture": os.uname().machine,
            "boundary": {
                "sandbox": "macos-seatbelt",
                "policy_mode": "deny-default",
                "network_rule": "deny network*",
                "transport": "anonymous_inherited_unix_socketpair",
                "peer_count": 2,
                "environment_keys": sorted(environment),
                "environment_sha256": environment_sha256,
                "policy_sha256": policy_sha256,
                "source_sha256": identities["source"].sha256,
                "python_executable_sha256": identities["python"].sha256,
                "sandbox_exec_sha256": identities["sandbox"].sha256,
                "limits": {
                    "core_bytes": 0,
                    "file_bytes": 0,
                    "open_files": MAX_OPEN_FILES,
                },
            },
            "controls": {
                "positive_control_scope": "supervisor_outside_seatbelt",
                "dns_positive_control": "resolved",
                "tcp_positive_control": "connected",
                "dns_attempted": 2,
                "dns_denied": 2,
                "tcp_attempted": 2,
                "tcp_denied": 2,
                "total_attempted": 4,
                "total_denied": 4,
                "sandbox_network_successes": 0,
                "unexpected_attempts": 0,
                "listener_positive_control_connections": positive_connections,
                "listener_sandbox_connections": sandbox_connections,
            },
            "processes": reports,
            "sentinel": {
                "kind": "public_synthetic_canary",
                "input_sha256": payload_sha256,
                "receipt_occurrences": 0,
                "child_stdout_occurrences": sum(
                    chunk.count(selected_sentinel.encode("utf-8")) for chunk in stdout_chunks
                ),
                "child_stderr_occurrences": sum(
                    chunk.count(selected_sentinel.encode("utf-8")) for chunk in stderr_chunks
                ),
                "control_report_occurrences": sum(
                    _canonical_bytes(report).count(selected_sentinel.encode("utf-8"))
                    for report in reports
                ),
            },
            "nonclaims": list(NONCLAIMS),
        }
        if selected_sentinel.encode("utf-8") in _canonical_bytes(receipt_body):
            raise FrontierBoundaryError("synthetic sentinel reached the public receipt")
        receipt = {**receipt_body, "receipt_sha256": _canonical_hash(receipt_body)}
        validate_frontier_egress_receipt(receipt)
        return receipt
    finally:
        _terminate(processes)
        for channel in (
            runner_peer,
            model_peer,
            runner_control_parent,
            runner_control_child,
            model_control_parent,
            model_control_child,
            listener,
        ):
            with contextlib.suppress(OSError):
                channel.close()


def validate_frontier_egress_receipt(value: Mapping[str, Any]) -> None:
    """Validate the complete public receipt allowlist and its self-hash."""

    if set(value) != RECEIPT_KEYS:
        raise FrontierBoundaryError("receipt fields differ from the public allowlist")
    body = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if value.get("receipt_sha256") != _canonical_hash(body):
        raise FrontierBoundaryError("receipt self-hash mismatch")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("gate") != GATE
        or value.get("status") != "VALID"
        or value.get("evidence_scope") != EVIDENCE_SCOPE
        or value.get("platform") != "darwin"
        or not isinstance(value.get("architecture"), str)
        or not value["architecture"]
        or value.get("nonclaims") != list(NONCLAIMS)
    ):
        raise FrontierBoundaryError("receipt identity or nonclaims mismatch")

    boundary = value.get("boundary")
    if not isinstance(boundary, dict) or set(boundary) != BOUNDARY_KEYS:
        raise FrontierBoundaryError("receipt boundary fields differ from the allowlist")
    if (
        boundary.get("sandbox") != "macos-seatbelt"
        or boundary.get("policy_mode") != "deny-default"
        or boundary.get("network_rule") != "deny network*"
        or boundary.get("transport") != "anonymous_inherited_unix_socketpair"
        or boundary.get("peer_count") != 2
        or boundary.get("environment_keys") != sorted(FIXED_CHILD_ENVIRONMENT)
        or boundary.get("environment_sha256") != _canonical_hash(FIXED_CHILD_ENVIRONMENT)
        or not all(
            SHA256_RE.fullmatch(str(boundary.get(key)))
            for key in (
                "policy_sha256",
                "source_sha256",
                "python_executable_sha256",
                "sandbox_exec_sha256",
            )
        )
    ):
        raise FrontierBoundaryError("receipt boundary values are invalid")
    current_source = _measure_regular_file(SOURCE_PATH, "receipt source")
    current_python = _measure_regular_file(Path(sys.executable), "receipt Python executable")
    current_sandbox = _measure_regular_file(SANDBOX_EXEC, "receipt sandbox-exec")
    current_policy = build_sandbox_policy(
        source_path=current_source.path,
        python_executable=current_python.path,
    )
    if (
        boundary["source_sha256"] != current_source.sha256
        or boundary["python_executable_sha256"] != current_python.sha256
        or boundary["sandbox_exec_sha256"] != current_sandbox.sha256
        or boundary["policy_sha256"] != _raw_hash(current_policy.encode("utf-8"))
    ):
        raise FrontierBoundaryError("receipt does not bind the current executable boundary")
    limits = boundary.get("limits")
    if (
        not isinstance(limits, dict)
        or set(limits) != LIMIT_KEYS
        or limits
        != {
            "core_bytes": 0,
            "file_bytes": 0,
            "open_files": MAX_OPEN_FILES,
        }
    ):
        raise FrontierBoundaryError("receipt resource limits are invalid")

    controls = value.get("controls")
    if (
        not isinstance(controls, dict)
        or set(controls) != CONTROL_KEYS
        or controls
        != {
            "positive_control_scope": "supervisor_outside_seatbelt",
            "dns_positive_control": "resolved",
            "tcp_positive_control": "connected",
            "dns_attempted": 2,
            "dns_denied": 2,
            "tcp_attempted": 2,
            "tcp_denied": 2,
            "total_attempted": 4,
            "total_denied": 4,
            "sandbox_network_successes": 0,
            "unexpected_attempts": 0,
            "listener_positive_control_connections": 1,
            "listener_sandbox_connections": 0,
        }
    ):
        raise FrontierBoundaryError("receipt canary controls are invalid")

    processes = value.get("processes")
    if not isinstance(processes, list) or len(processes) != 2:
        raise FrontierBoundaryError("receipt must contain two process reports")
    if [item.get("role") for item in processes if isinstance(item, dict)] != list(ROLES):
        raise FrontierBoundaryError("receipt process roles are invalid")
    pids: list[int] = []
    for process in processes:
        if not isinstance(process, dict) or set(process) != PROCESS_KEYS:
            raise FrontierBoundaryError("receipt process fields differ from the allowlist")
        pid = process.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
            raise FrontierBoundaryError("receipt process PID is invalid")
        pids.append(pid)
        if (
            process.get("policy_sha256") != boundary["policy_sha256"]
            or process.get("environment_sha256") != boundary["environment_sha256"]
            or process.get("source_sha256") != boundary["source_sha256"]
            or process.get("python_executable_sha256") != boundary["python_executable_sha256"]
            or process.get("fd_roster_valid") is not True
            or process.get("observed_fd_count") != 5
            or process.get("core_limit_zero") is not True
            or process.get("file_limit_zero") is not True
            or process.get("open_file_limit") != MAX_OPEN_FILES
            or process.get("peer_socket_valid") is not True
            or process.get("control_socket_valid") is not True
            or process.get("work_channel") != "valid"
            or process.get("dns_canary", {}).get("status") != "denied"
            or process.get("tcp_canary")
            != {"status": "denied", "error_class": "PermissionError", "errno": errno.EPERM}
        ):
            raise FrontierBoundaryError("receipt process boundary proof is invalid")
        _require_sha256(process.get("payload_sha256"), "process payload_sha256")
    if len(set(pids)) != 2 or processes[0]["payload_sha256"] != processes[1]["payload_sha256"]:
        raise FrontierBoundaryError("receipt peer identity or payload binding is invalid")

    sentinel = value.get("sentinel")
    if not isinstance(sentinel, dict) or set(sentinel) != SENTINEL_KEYS:
        raise FrontierBoundaryError("receipt sentinel fields differ from the allowlist")
    if sentinel != {
        "kind": "public_synthetic_canary",
        "input_sha256": processes[0]["payload_sha256"],
        "receipt_occurrences": 0,
        "child_stdout_occurrences": 0,
        "child_stderr_occurrences": 0,
        "control_report_occurrences": 0,
    }:
        raise FrontierBoundaryError("receipt sentinel scan is invalid")


def _main(argv: Sequence[str] | None = None) -> int:
    arguments = tuple(sys.argv if argv is None else argv)
    if len(arguments) >= 2 and arguments[1] == "--isolated-child":
        return _isolated_child_main(arguments)
    return 64


if __name__ == "__main__":
    raise SystemExit(_main())
