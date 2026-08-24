"""Exact L70.2 broker service/lifecycle denominator: ten local cases only."""

from __future__ import annotations

import copy
import hashlib
import inspect
import plistlib
import socket
import stat
import struct
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime import w3_broker_protocol as protocol  # noqa: E402
from runtime import w3_broker_service as service  # noqa: E402
from runtime import w3_protected_broker as core  # noqa: E402

# Public RFC 8032 KAT seeds only; they are deterministic fixtures, never installed keys.
_SEED_ONE = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
_SEED_TWO = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
BROKER_PLIST = PROJECT_ROOT / "packaging/launchd/com.metis.model1.w3-broker.plist.in"


def _digest(seed: str | bytes) -> str:
    payload = seed.encode() if isinstance(seed, str) else seed
    return protocol.SHA256_PREFIX + hashlib.sha256(payload).hexdigest()


def _row(path: str, digest: str) -> dict[str, object]:
    return {
        "path": path,
        "size": 4096,
        "mode": stat.S_IFREG | 0o444,
        "sha256": digest,
        "uid": 0,
        "gid": 0,
        "dev": 1,
        "ino": int(hashlib.sha256(path.encode()).hexdigest()[:8], 16),
        "nlink": 1,
    }


def _authority(seed: bytes = _SEED_ONE, *, release_id: str = "protected-public-v1") -> dict:
    public_key = protocol.ed25519.derive_public_key(seed)
    key_id = protocol.ed25519.mode_scoped_key_id(
        public_key,
        mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
    )
    installed = {
        "broker_code_sha256": _digest("broker"),
        "launcher_sha256": _digest("launcher"),
        "worker_sha256": _digest("worker"),
        "loader_sha256": _digest("loader"),
        "runner_sha256": _digest("runner"),
        "node_sha256": _digest("node"),
    }
    paths = {
        "broker": "broker/main.py",
        "launcher": "launcher/w3",
        "worker": "broker/runtime/w3_installed_worker.py",
        "loader": "loader/native.mjs",
        "runner": "release/runtime/metis_oracle/runner.ts",
        "node": "node/bin/node",
    }
    roster = sorted(
        [
            _row(paths[role], installed[protocol.ROLE_DIGEST_FIELD[role]])
            for role in protocol.INSTALLED_CODE_ROLES
        ]
        + [_row("runtime/policy.sb", _digest("policy"))],
        key=lambda row: row["path"],
    )
    policy_template = _digest("policy-template")
    policy_parameters = {"NODE_SHA256": installed["node_sha256"]}
    authority = {
        "schema_version": protocol.SCHEMA_VERSION,
        "kind": protocol.KIND_AUTHORITY,
        "authority_id": protocol.AUTHORITY_ID,
        "mode": protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
        "signing": {
            "algorithm": protocol.PRODUCTION_ALGORITHM,
            "key_id": key_id,
            "public_key": protocol.ed25519.encode_public_key(public_key),
        },
        "broker_identity": {"user": "_metisbroker", "uid": 499, "gid": 499},
        "runner_identity": {"user": "_metisrunner", "uid": 498, "gid": 498},
        "launcher_identity": {"user": "root", "uid": 0, "gid": 0},
        "installed_code_identity": installed,
        "installed_code_paths": paths,
        "installed_code_roster": roster,
        "policy_identity": {
            "template_sha256": policy_template,
            "parameters": policy_parameters,
            "resolved_sha256": protocol.policy_hash(policy_template, policy_parameters),
        },
        "release_identity": {"release_id": release_id, "ancestry_root_sha256": ""},
    }
    authority["release_identity"]["ancestry_root_sha256"] = protocol.release_ancestry_hash(
        release_id,
        roster,
    )
    return protocol.validate_authority(authority)


def _request(authority: Mapping[str, object], nonce: str) -> dict:
    return protocol.build_request(
        client_nonce=nonce,
        payload={"task": "protected-public-fixture", "inputs": {"source": _digest("source")}},
        claimed_authority_sha256=protocol.authority_hash(authority),
        claimed_release_sha256=authority["release_identity"]["ancestry_root_sha256"],
        claimed_policy_sha256=authority["policy_identity"]["resolved_sha256"],
    )


def _synthetic_authority() -> dict:
    authority = copy.deepcopy(_authority())
    authority["mode"] = protocol.MODE_SYNTHETIC
    authority["signing"] = {
        "algorithm": protocol.SYNTHETIC_ALGORITHM,
        "key_id": protocol.synthetic_key_id(),
    }
    return protocol.validate_authority(authority)


def _result(request: Mapping[str, object], authority: Mapping[str, object]) -> dict:
    installed = authority["installed_code_identity"]
    roster = copy.deepcopy(authority["installed_code_roster"])
    return {
        "measured": {
            "authority_sha256": protocol.authority_hash(authority),
            "release_sha256": authority["release_identity"]["ancestry_root_sha256"],
            "policy_sha256": request["claimed_policy_sha256"],
        },
        "identities": {
            "broker": {"user": "_metisbroker", "code_sha256": installed["broker_code_sha256"]},
            "launcher": {"code_sha256": installed["launcher_sha256"]},
            "worker": {"code_sha256": installed["worker_sha256"]},
            "node": {"sha256": installed["node_sha256"], "version": "v22.22.3"},
            "loader": {"sha256": installed["loader_sha256"]},
        },
        "effective_ids": {
            "broker_uid": authority["broker_identity"]["uid"],
            "broker_gid": authority["broker_identity"]["gid"],
            "runner_uid": authority["runner_identity"]["uid"],
            "runner_gid": authority["runner_identity"]["gid"],
            "launcher_uid": 0,
            "launcher_gid": 0,
        },
        "policy": copy.deepcopy(authority["policy_identity"]),
        "roster": {"pre": roster, "post": copy.deepcopy(roster)},
        "output": {
            "stdout_sha256": _digest("stdout"),
            "stderr_sha256": _digest("stderr"),
            "exit_code": 0,
            "publication": {"sha256": _digest("publication"), "size": 1, "atomic": True},
        },
        "cleanup": {
            "process_census": {"residual_children": 0, "census_sha256": _digest("process")},
            "fd_census": {"retained_fds": 0, "census_sha256": _digest("fds")},
            "temp_census": {"entries": [], "roster_sha256": _digest("temp")},
        },
    }


def _executor(calls: list[str] | None = None) -> Callable:
    def execute(request: Mapping[str, object], authority: Mapping[str, object], _attempt: Mapping):
        if calls is not None:
            calls.append(str(request["client_nonce"]))
        return _result(request, authority)

    return execute


def _signer(seed: bytes, calls: list[bytes] | None = None) -> Callable:
    key_id = protocol.ed25519.mode_scoped_key_id(
        protocol.ed25519.derive_public_key(seed),
        mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
    )

    def sign(receipt: Mapping[str, object]) -> Mapping[str, object]:
        if calls is not None:
            calls.append(protocol.receipt_signing_bytes(receipt))
        return protocol.attach_protected_public_synthetic_signature(
            receipt,
            private_key=seed,
            registered_key_id=key_id,
        )

    return sign


def _broker(
    directory: Path,
    authority: dict,
    *,
    seed: bytes = _SEED_ONE,
    executor: Callable | None = None,
    signer: Callable | None = None,
    registry: Mapping[str, bytes] | None = None,
) -> core.ProtectedExecutionBroker:
    directory.mkdir(parents=True, exist_ok=True)
    key_id = str(authority["signing"]["key_id"])
    public_key = protocol.ed25519.decode_public_key(authority["signing"]["public_key"])
    return core.ProtectedExecutionBroker(
        authority=authority,
        ledger_path=directory / "ledger.bin",
        executor=executor or _executor(),
        protected_signer=signer or _signer(seed),
        verification_keys=registry if registry is not None else {key_id: public_key},
        nonce_factory=lambda: "b2" * 32,
        require_existing_ledger=False,
        allow_unprotected_test_ledger=True,
    )


def test_protected_core_signs_exact_mode_flag_and_nonclaims(tmp_path: Path) -> None:
    authority = _authority()
    receipt = protocol.parse_canonical_json(
        _broker(tmp_path, authority).handle(
            protocol.canonical_bytes(_request(authority, "01" * 32))
        )
    )
    assert receipt["mode"] == protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC
    assert receipt["executed_preimage_authority"] is True
    assert tuple(receipt["nonclaims"]) == protocol.PROTECTED_PUBLIC_SYNTHETIC_NONCLAIMS
    public_key = protocol.ed25519.decode_public_key(authority["signing"]["public_key"])
    assert protocol.verify_receipt_signature(
        receipt,
        public_key=public_key,
        registered_key_id=authority["signing"]["key_id"],
    )


def test_production_missing_signer_and_missing_current_key_fail_pre_effect(tmp_path: Path) -> None:
    authority = _authority()
    executor_calls: list[str] = []
    production = copy.deepcopy(authority)
    production["mode"] = protocol.MODE_PRODUCTION
    production["signing"] = {
        "algorithm": protocol.PRODUCTION_ALGORITHM,
        "key_id": protocol.ed25519.mode_scoped_key_id(
            protocol.ed25519.decode_public_key(authority["signing"]["public_key"]),
            mode=protocol.MODE_PRODUCTION,
        ),
    }
    with pytest.raises(core.BrokerCoreError, match="PRODUCTION_MODE_FORBIDDEN"):
        core.ProtectedExecutionBroker(
            authority=production,
            ledger_path=tmp_path / "production.bin",
            executor=_executor(executor_calls),
        )
    with pytest.raises(core.BrokerCoreError, match="PROTECTED_SIGNER_REQUIRED"):
        core.ProtectedExecutionBroker(
            authority=authority,
            ledger_path=tmp_path / "missing-signer.bin",
            executor=_executor(executor_calls),
            verification_keys={
                authority["signing"]["key_id"]: protocol.ed25519.decode_public_key(
                    authority["signing"]["public_key"]
                )
            },
        )
    with pytest.raises(core.BrokerCoreError, match="PROTECTED_CURRENT_KEY_NOT_REGISTERED"):
        core.ProtectedExecutionBroker(
            authority=authority,
            ledger_path=tmp_path / "missing-key.bin",
            executor=_executor(executor_calls),
            protected_signer=_signer(_SEED_ONE),
            verification_keys={},
        )
    assert executor_calls == []
    assert list(tmp_path.glob("*.bin")) == []


def test_signer_mutation_and_mode_scoped_key_mismatch_never_append_receipt(
    tmp_path: Path,
) -> None:
    authority = _authority()

    def mutating_signer(receipt: Mapping[str, object]) -> Mapping[str, object]:
        mutated = copy.deepcopy(receipt)
        mutated["output"]["exit_code"] = 1
        return protocol.attach_protected_public_synthetic_signature(
            mutated,
            private_key=_SEED_ONE,
            registered_key_id=authority["signing"]["key_id"],
        )

    broker = _broker(tmp_path / "mutated", authority, signer=mutating_signer)
    with pytest.raises(core.BrokerCoreError, match="PROTECTED_SIGNER_MUTATED_SIGNED_FIELDS"):
        broker.handle(protocol.canonical_bytes(_request(authority, "02" * 32)))
    assert [row["record_kind"] for row in broker.inspect_ledger()] == ["attempt", "tombstone"]

    wrong_signer = _signer(_SEED_TWO)
    mismatched = _broker(tmp_path / "wrong-key", authority, signer=wrong_signer)
    with pytest.raises(core.BrokerCoreError, match="PROTECTED_SIGNER_KEY_MISMATCH"):
        mismatched.handle(protocol.canonical_bytes(_request(authority, "03" * 32)))
    assert not any(row["record_kind"] == "receipt" for row in mismatched.inspect_ledger())


def test_protected_restart_returns_exact_receipt_without_reexecution_or_resigning(
    tmp_path: Path,
) -> None:
    authority = _authority()
    executor_calls: list[str] = []
    signer_calls: list[bytes] = []
    request = protocol.canonical_bytes(_request(authority, "04" * 32))
    first_broker = _broker(
        tmp_path,
        authority,
        executor=_executor(executor_calls),
        signer=_signer(_SEED_ONE, signer_calls),
    )
    first = first_broker.handle(request)
    restarted = _broker(
        tmp_path,
        authority,
        executor=_executor(executor_calls),
        signer=_signer(_SEED_ONE, signer_calls),
    )
    assert restarted.handle(request) == first
    assert restarted.handle(request) == first
    assert executor_calls == ["04" * 32]
    assert len(signer_calls) == 1


def test_recovery_requires_every_historical_protected_public_key(tmp_path: Path) -> None:
    old_authority = _authority(_SEED_ONE, release_id="protected-old")
    old = _broker(tmp_path, old_authority)
    old.handle(protocol.canonical_bytes(_request(old_authority, "05" * 32)))

    new_authority = _authority(_SEED_TWO, release_id="protected-new")
    new_key_id = str(new_authority["signing"]["key_id"])
    new_public = protocol.ed25519.decode_public_key(new_authority["signing"]["public_key"])
    missing_old = _broker(
        tmp_path,
        new_authority,
        seed=_SEED_TWO,
        registry={new_key_id: new_public},
    )
    with pytest.raises(core.BrokerCoreError, match="LEDGER_CORRUPT.*unknown-protected-key"):
        missing_old.inspect_ledger()

    old_key_id = str(old_authority["signing"]["key_id"])
    old_public = protocol.ed25519.decode_public_key(old_authority["signing"]["public_key"])
    complete = _broker(
        tmp_path,
        new_authority,
        seed=_SEED_TWO,
        registry={old_key_id: old_public, new_key_id: new_public},
    )
    receipt = protocol.parse_canonical_json(
        complete.handle(protocol.canonical_bytes(_request(new_authority, "06" * 32)))
    )
    assert receipt["receipt_sequence"] == 2

    mixed_directory = tmp_path / "mixed-mode"
    mixed_directory.mkdir()
    synthetic_authority = _synthetic_authority()
    synthetic = core.ProtectedExecutionBroker(
        authority=synthetic_authority,
        ledger_path=mixed_directory / "ledger.bin",
        executor=_executor(),
        nonce_factory=lambda: "a1" * 32,
        require_existing_ledger=False,
        allow_unprotected_test_ledger=True,
    )
    synthetic.handle(protocol.canonical_bytes(_request(synthetic_authority, "0c" * 32)))
    protected_on_synthetic = _broker(mixed_directory, old_authority)
    with pytest.raises(core.BrokerCoreError, match="LEDGER_CORRUPT.*ledger-mode-mismatch"):
        protected_on_synthetic.inspect_ledger()


# Tests 6-10 below exercise the FD3 service and exact native launcher envelope.


class _MemorySocket:
    def __init__(self, incoming: bytes = b"", *, peer: tuple[int, int] = (0, 0)):
        self.incoming = bytearray(incoming)
        self.sent = bytearray()
        self.shutdown_calls: list[int] = []
        self.closed = False
        self.peer = peer

    def recv(self, count: int) -> bytes:
        if not self.incoming:
            return b""
        chunk = bytes(self.incoming[:count])
        del self.incoming[:count]
        return chunk

    def sendall(self, payload: bytes) -> None:
        self.sent.extend(payload)

    def shutdown(self, how: int) -> None:
        self.shutdown_calls.append(how)

    def close(self) -> None:
        self.closed = True

    def getsockopt(self, level: int, option: int, count: int = 0) -> bytes:
        assert level == service.SOL_LOCAL
        assert option == socket.LOCAL_PEERCRED
        assert count == service.XUCRED_BYTES
        uid, gid = self.peer
        groups = [gid, *([0] * 15)]
        return struct.pack(
            service.XUCRED_FORMAT,
            service.XUCRED_VERSION,
            uid,
            1,
            *groups,
        )


class _MemoryListener:
    def __init__(self, connections: list[_MemorySocket]):
        self.connections = list(connections)
        self.closed = False
        self.family = socket.AF_UNIX

    def getsockopt(self, level: int, option: int) -> int:
        assert level == socket.SOL_SOCKET
        assert option == socket.SO_TYPE
        return socket.SOCK_STREAM

    def getsockname(self) -> str:
        return service.BROKER_SOCKET_PATH

    def accept(self) -> tuple[_MemorySocket, object]:
        return self.connections.pop(0), object()

    def close(self) -> None:
        self.closed = True


class _StaticBroker:
    def __init__(self, response: bytes):
        self.response = response
        self.requests: list[bytes] = []

    def handle(self, canonical_request: bytes) -> bytes:
        self.requests.append(canonical_request)
        return self.response


def _native_payload(
    *,
    stdout: bytes = b"fixture-output",
    stderr: bytes = b"",
    flags: int | None = None,
    wait_kind: int = service.WAIT_EXITED,
    wait_value: int = 0,
    process_group_residual: int = 0,
    retained_fds: int = 0,
    temp_entries: int = 0,
    broker_peer_uid: int = 499,
    broker_peer_gid: int = 499,
    launcher_actual_uid: int = 0,
    launcher_actual_gid: int = 0,
    runner_target_uid: int = 498,
    runner_target_gid: int = 498,
    child_boundary_succeeded: int = 1,
) -> tuple[bytes, str]:
    if flags is None:
        flags = service.FLAG_EXITED | service.REQUIRED_CLEANUP_FLAGS
    cleanup = service.NATIVE_CLEANUP_MAGIC + struct.pack(
        ">16I",
        service.NATIVE_RESULT_VERSION,
        flags,
        process_group_residual,
        retained_fds,
        temp_entries,
        wait_kind,
        wait_value,
        len(stdout),
        len(stderr),
        broker_peer_uid,
        broker_peer_gid,
        launcher_actual_uid,
        launcher_actual_gid,
        runner_target_uid,
        runner_target_gid,
        child_boundary_succeeded,
    )
    payload = (
        service.NATIVE_RESULT_MAGIC
        + struct.pack(
            ">7I",
            service.NATIVE_RESULT_VERSION,
            flags,
            wait_kind,
            wait_value,
            len(stdout),
            len(stderr),
            len(cleanup),
        )
        + stdout
        + stderr
        + cleanup
    )
    return payload, _digest(cleanup)


def _launcher_response(
    request: Mapping[str, object],
    attempt: Mapping[str, object],
    *,
    status: int = protocol.STATUS_OK,
    request_sha256: str | None = None,
    broker_nonce: str | None = None,
    cleanup_sha256: str | None = None,
    payload: bytes | None = None,
) -> bytes:
    native_payload, native_cleanup = _native_payload() if payload is None else (payload, None)
    if cleanup_sha256 is None:
        if native_cleanup is None:
            raise AssertionError("explicit cleanup digest required for custom payload")
        cleanup_sha256 = native_cleanup
    return protocol.encode_response_frame(
        native_payload,
        status=status,
        request_sha256=request_sha256 or str(request["request_hash"]),
        broker_nonce=broker_nonce or str(attempt["broker_nonce"]),
        cleanup_sha256=cleanup_sha256,
    )


def test_fd3_daemon_uses_inherited_stream_without_bind_or_unlink(monkeypatch) -> None:
    authority = _authority()
    canonical_request = protocol.canonical_bytes(_request(authority, "07" * 32))
    canonical_response = protocol.canonical_bytes({"accepted": True})
    connection = _MemorySocket(
        service.encode_service_envelope(canonical_request),
        peer=(service.CALLER_UID, service.CALLER_GID),
    )
    listener = _MemoryListener([connection])
    constructed: list[dict] = []

    def socket_factory(*_args, **kwargs):
        constructed.append(kwargs)
        return listener

    monkeypatch.setattr(service.socket, "socket", socket_factory)
    broker = _StaticBroker(canonical_response)
    service.serve_inherited_fd3(broker, max_connections=1)
    assert constructed == [{"fileno": service.BROKER_LISTENER_FD}]
    assert broker.requests == [canonical_request]
    assert connection.shutdown_calls == [socket.SHUT_WR]
    assert connection.closed and listener.closed
    source = inspect.getsource(service)
    assert ".bind(" not in source and ".unlink(" not in source
    plist = plistlib.loads(BROKER_PLIST.read_bytes())
    assert plist["ProgramArguments"] == [
        "/Library/Application Support/MetisModel1/broker/bin/w3-broker-socket-shim"
    ]
    assert plist["Sockets"] == {
        "BrokerListener": {
            "SockPathName": "/var/run/metis-model1/w3-broker.sock",
            "SockPathOwner": 501,
            "SockPathGroup": 20,
            "SockPathMode": 0o600,
        }
    }
    assert plist["StandardOutPath"].startswith("/Library/Logs/MetisModel1/broker/")

    denied = _MemorySocket(
        service.encode_service_envelope(canonical_request),
        peer=(service.CALLER_UID, service.CALLER_GID + 1),
    )
    denied_listener = _MemoryListener([denied])
    service.serve_listener(denied_listener, broker, max_connections=1)
    assert broker.requests == [canonical_request]


def test_service_envelope_rejects_truncated_oversize_and_trailing_before_core() -> None:
    broker = _StaticBroker(b"unused")
    attacks = (
        b"\x00\x00",
        struct.pack(">I", 0),
        struct.pack(">I", service.MAX_SERVICE_BYTES + 1),
        struct.pack(">I", 8) + b"short",
        service.encode_service_envelope(b"{}") + b"trailing",
        service.encode_service_envelope(b"{}") + service.encode_service_envelope(b"{}"),
    )
    for attack in attacks:
        with pytest.raises(service.BrokerServiceError):
            service.handle_service_connection(_MemorySocket(attack), broker)
    assert broker.requests == []


def test_launcher_transport_uses_fixed_path_exact_frame_and_shutdown_write() -> None:
    authority = _authority()
    request = _request(authority, "08" * 32)
    attempt = {"broker_nonce": "b2" * 32}
    response = _launcher_response(request, attempt)
    connection = _MemorySocket(response)
    connected_paths: list[str] = []

    def connector(path: str) -> _MemorySocket:
        connected_paths.append(path)
        return connection

    observed_native: list[service.NativeLauncherResult] = []

    inner_payload = protocol.canonical_bytes({"schema_version": 1, "source": "public"})

    def payload_adapter(adapter_request, adapter_authority, adapter_attempt):
        assert adapter_request == request
        assert adapter_authority == authority
        assert adapter_attempt == attempt
        return service.PreparedLauncherPayload(inner_payload, {"pre": True})

    def adapter(native, prepared, adapter_request, adapter_authority, adapter_attempt):
        observed_native.append(native)
        assert prepared.context == {"pre": True}
        assert adapter_request == request
        assert adapter_authority == authority
        assert adapter_attempt == attempt
        result = _result(request, authority)
        result["output"]["stdout_sha256"] = _digest(native.stdout)
        result["output"]["stderr_sha256"] = _digest(native.stderr)
        result["output"]["exit_code"] = native.wait_value
        cleanup_sha256 = _digest(native.cleanup_record)
        result["cleanup"]["process_census"]["census_sha256"] = cleanup_sha256
        result["cleanup"]["fd_census"]["census_sha256"] = cleanup_sha256
        result["cleanup"]["temp_census"]["roster_sha256"] = cleanup_sha256
        return result

    result = service.FixedLauncherTransport(
        payload_adapter=payload_adapter,
        result_adapter=adapter,
        connector=connector,
    )(request, authority, attempt)
    assert result["output"]["stdout_sha256"] == _digest(b"fixture-output")
    assert connected_paths == [service.LAUNCHER_SOCKET_PATH]
    assert connection.shutdown_calls == [socket.SHUT_WR]
    sent = protocol.decode_request_frame(bytes(connection.sent))
    assert sent.payload == inner_payload
    assert sent.request_sha256 == request["request_hash"]
    assert sent.authority_sha256 == protocol.authority_hash(authority)
    assert sent.release_sha256 == authority["release_identity"]["ancestry_root_sha256"]
    assert sent.broker_nonce == attempt["broker_nonce"]
    assert len(observed_native) == 1 and observed_native[0].stdout == b"fixture-output"
    assert observed_native[0].broker_peer_uid == 499
    assert observed_native[0].runner_target_uid == 498
    assert observed_native[0].child_boundary_succeeded is True


def test_launcher_response_status_correlation_cleanup_and_eof_mutations_fail_closed() -> None:
    authority = _authority()
    request = _request(authority, "09" * 32)
    attempt = {"broker_nonce": "b2" * 32}
    payload, cleanup_digest = _native_payload()
    attacks = (
        _launcher_response(request, attempt, status=2),
        _launcher_response(request, attempt, request_sha256=_digest("wrong-request")),
        _launcher_response(request, attempt, broker_nonce="c3" * 32),
        _launcher_response(
            request,
            attempt,
            payload=payload,
            cleanup_sha256=_digest("wrong-cleanup"),
        ),
        _launcher_response(request, attempt) + b"trailing",
        _launcher_response(
            request,
            attempt,
            payload=_native_payload(flags=service.FLAG_EXITED)[0],
            cleanup_sha256=_native_payload(flags=service.FLAG_EXITED)[1],
        ),
    )
    adapter_calls: list[int] = []
    for encoded in attacks:
        connection = _MemorySocket(encoded)
        transport = service.FixedLauncherTransport(
            payload_adapter=lambda *_args: service.PreparedLauncherPayload(b"{}", None),
            result_adapter=lambda *_args: adapter_calls.append(1) or {},
            connector=lambda _path, connection=connection: connection,
        )
        with pytest.raises(service.BrokerServiceError):
            transport(request, authority, attempt)
    assert adapter_calls == []
    assert cleanup_digest.startswith(protocol.SHA256_PREFIX)

    wrong_peer = _MemorySocket(_launcher_response(request, attempt), peer=(501, 501))
    with pytest.raises(service.BrokerServiceError, match="LAUNCHER_PEER_NOT_ROOT"):
        service.FixedLauncherTransport(
            payload_adapter=lambda *_args: service.PreparedLauncherPayload(b"{}", None),
            result_adapter=lambda *_args: {},
            connector=lambda _path: wrong_peer,
        )(request, authority, attempt)

    unbound_output = _MemorySocket(_launcher_response(request, attempt))
    with pytest.raises(service.BrokerServiceError, match="RESULT_ADAPTER_OUTPUT_MISMATCH"):
        service.FixedLauncherTransport(
            payload_adapter=lambda *_args: service.PreparedLauncherPayload(b"{}", None),
            result_adapter=lambda *_args: _result(request, authority),
            connector=lambda _path: unbound_output,
        )(request, authority, attempt)

    for mutated in (
        {"child_boundary_succeeded": 0},
        {"broker_peer_uid": 501},
        {"launcher_actual_uid": 1},
        {"runner_target_uid": 499},
    ):
        bad_payload, bad_cleanup = _native_payload(**mutated)
        bad_connection = _MemorySocket(
            _launcher_response(
                request,
                attempt,
                payload=bad_payload,
                cleanup_sha256=bad_cleanup,
            )
        )
        with pytest.raises(service.BrokerServiceError):
            service.FixedLauncherTransport(
                payload_adapter=lambda *_args: service.PreparedLauncherPayload(b"{}", None),
                result_adapter=lambda *_args: _result(request, authority),
                connector=lambda _path, connection=bad_connection: connection,
            )(request, authority, attempt)


def test_protected_executor_failure_tombstones_without_signature_or_receipt_gap(
    tmp_path: Path,
) -> None:
    authority = _authority()
    signer_calls: list[bytes] = []
    executor_calls: list[str] = []

    def fail_first(request, loaded_authority, _attempt):
        executor_calls.append(str(request["client_nonce"]))
        if request["client_nonce"] == "0a" * 32:
            raise service.BrokerServiceError("LAUNCHER_STATUS", "5")
        return _result(request, loaded_authority)

    broker = _broker(
        tmp_path,
        authority,
        executor=fail_first,
        signer=_signer(_SEED_ONE, signer_calls),
    )
    with pytest.raises(core.BrokerCoreError, match="EXECUTOR_FAILED"):
        broker.handle(protocol.canonical_bytes(_request(authority, "0a" * 32)))
    receipt = protocol.parse_canonical_json(
        broker.handle(protocol.canonical_bytes(_request(authority, "0b" * 32)))
    )
    assert (receipt["attempt_sequence"], receipt["receipt_sequence"]) == (2, 1)
    assert [row["record_kind"] for row in broker.inspect_ledger()] == [
        "attempt",
        "tombstone",
        "attempt",
        "receipt",
    ]
    assert executor_calls == ["0a" * 32, "0b" * 32]
    assert len(signer_calls) == 1

    crash_signer_calls: list[bytes] = []
    crash_directory = tmp_path / "after-sign-crash"
    crash_request = protocol.canonical_bytes(_request(authority, "0d" * 32))
    crashing = _broker(
        crash_directory,
        authority,
        signer=_signer(_SEED_ONE, crash_signer_calls),
    )
    with pytest.raises(core.InjectedCrash, match="after_sign"):
        crashing.handle(crash_request, crash_at="after_sign")
    restarted = _broker(
        crash_directory,
        authority,
        signer=_signer(_SEED_ONE, crash_signer_calls),
    )
    with pytest.raises(core.BrokerCoreError, match="NONCE_CONSUMED_NO_RECEIPT"):
        restarted.handle(crash_request)
    assert len(crash_signer_calls) == 1
    assert not any(row["record_kind"] == "receipt" for row in restarted.inspect_ledger())
