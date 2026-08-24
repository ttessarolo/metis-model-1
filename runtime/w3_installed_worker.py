#!/usr/bin/env python3
"""Fixed broker-side worker for the installed protected-public W3 service.

``worker`` is a Python code role executed as ``_metisbroker``.  It is not the
Node child.  It maps one root-owned public-fixture selector to a canonical
oracle request, measures the full installed roster before and after the native
boundary, parses the real runner result and publishes the exact bytes through
an inode-anchored, no-clobber directory.  The root launcher remains opaque: it
receives bytes and never parses this JSON.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import stat
import struct
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from runtime import w3_broker_protocol as protocol
from runtime import w3_broker_service as service

FIXTURE_REGISTRY_KIND = "w3-public-fixture-registry"
FIXTURE_REGISTRY_VERSION = 1
PUBLIC_JOURNAL_MAX_RECORD_BYTES = protocol.MAX_PAYLOAD_BYTES
PUBLIC_JOURNAL_MAX_RECORDS = 65_536
PUBLIC_JOURNAL_MAX_BYTES = 64 * 1024 * 1024
RUNNER_RESULT_FIELDS = {
    "schema_version",
    "status",
    "endpoint",
    "diagnostics",
    "ast",
    "ir",
    "toolchain",
    "runtime",
    "failure",
}
RUNNER_RUNTIME_FIELDS = {
    "node",
    "node_path",
    "loader_path",
    "loader_sha256",
    "loader_flags",
    "runner_path",
    "snapshot_revision",
    "snapshot_tree",
    "tooling_package_sha256",
    "tooling_lock_sha256",
    "node_modules_sha256",
    "node_binary_sha256",
    "sandbox_exec_path",
    "oracle_policy_version",
    "oracle_policy_sha256",
    "execution_policy_sha256",
}
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class InstalledWorkerError(RuntimeError):
    """Typed installed-worker refusal."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


class RosterProbe(Protocol):
    def __call__(self, authority: Mapping[str, object]) -> list[dict[str, object]]: ...


class PublicationWriter(Protocol):
    def __call__(self, name: str, payload: bytes) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class WorkerContext:
    pre_roster: tuple[dict[str, object], ...]
    broker_uid: int
    broker_gid: int
    oracle_request: Mapping[str, object]


def _sha256(payload: bytes) -> str:
    return protocol.SHA256_PREFIX + hashlib.sha256(payload).hexdigest()


def _path_parts(relative: str) -> tuple[str, ...]:
    if not isinstance(relative, str) or not relative or relative.startswith("/"):
        raise InstalledWorkerError("ROSTER_PATH_INVALID", str(relative))
    parts = PurePosixPath(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise InstalledWorkerError("ROSTER_PATH_INVALID", relative)
    return tuple(parts)


def _read_all(fd: int, expected_size: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, min(1024 * 1024, max(1, expected_size + 1 - total)))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > expected_size:
            raise InstalledWorkerError("ROSTER_SIZE_CHANGED")
    payload = b"".join(chunks)
    if len(payload) != expected_size:
        raise InstalledWorkerError("ROSTER_SIZE_CHANGED")
    return payload


class InstalledRosterProbe:
    """Measure exact authority paths below a descriptor-anchored install root."""

    def __init__(self, root: Path = Path("/"), *, path_map: Mapping[str, Path] | None = None):
        if not isinstance(root, Path) or not root.is_absolute():
            raise InstalledWorkerError("INSTALL_ROOT_INVALID")
        self._root = root
        self._path_map = None if path_map is None else dict(path_map)
        if self._path_map is not None:
            for logical, actual in self._path_map.items():
                _path_parts(logical)
                if (
                    not isinstance(actual, Path)
                    or not actual.is_absolute()
                    or "/Users/" in str(actual)
                ):
                    raise InstalledWorkerError("ROSTER_PATH_MAP_INVALID")

    @staticmethod
    def _validate_parent(info: os.stat_result) -> None:
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise InstalledWorkerError("ROSTER_ANCESTRY_UNPROTECTED")

    def _measure(self, root_fd: int, expected: Mapping[str, object]) -> dict[str, object]:
        logical = str(expected.get("path"))
        actual = self._path_map.get(logical) if self._path_map is not None else None
        parts = _path_parts(str(actual).lstrip("/") if actual is not None else logical)
        parent_fd = os.dup(root_fd)
        try:
            for part in parts[:-1]:
                next_fd = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
                )
                self._validate_parent(os.fstat(next_fd))
                os.close(parent_fd)
                parent_fd = next_fd
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
            try:
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_uid != 0
                    or info.st_gid != 0
                    or info.st_mode & 0o022
                ):
                    raise InstalledWorkerError("ROSTER_LEAF_UNPROTECTED", str(expected.get("path")))
                payload = _read_all(fd, info.st_size)
                row = {
                    "path": str(expected["path"]),
                    "size": info.st_size,
                    "mode": info.st_mode,
                    "sha256": _sha256(payload),
                    "uid": info.st_uid,
                    "gid": info.st_gid,
                    "dev": info.st_dev,
                    "ino": info.st_ino,
                    "nlink": info.st_nlink,
                }
                if row != dict(expected):
                    raise InstalledWorkerError(
                        "ROSTER_MEASUREMENT_MISMATCH", str(expected.get("path"))
                    )
                return row
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)

    def __call__(self, authority: Mapping[str, object]) -> list[dict[str, object]]:
        expected = authority.get("installed_code_roster")
        if not isinstance(expected, list) or not expected:
            raise InstalledWorkerError("ROSTER_AUTHORITY_INVALID")
        paths = [row.get("path") for row in expected if isinstance(row, Mapping)]
        if len(paths) != len(expected) or paths != sorted(paths) or len(set(paths)) != len(paths):
            raise InstalledWorkerError("ROSTER_AUTHORITY_INVALID")
        if self._path_map is not None and set(paths) != set(self._path_map):
            raise InstalledWorkerError("ROSTER_PATH_MAP_MISMATCH")
        root_fd = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            root_info = os.fstat(root_fd)
            self._validate_parent(root_info)
            return [self._measure(root_fd, row) for row in expected]
        finally:
            os.close(root_fd)


class AtomicPublicationWriter:
    """No-clobber publication below a precreated broker-owned active leaf."""

    def __init__(self, active_root: Path, *, broker_uid: int = 499, broker_gid: int = 499):
        if not isinstance(active_root, Path) or not active_root.is_absolute():
            raise InstalledWorkerError("PUBLICATION_ROOT_INVALID")
        self._active_root = active_root
        self._broker_uid = broker_uid
        self._broker_gid = broker_gid

    def __call__(self, name: str, payload: bytes) -> Mapping[str, object]:
        if not isinstance(name, str) or not name or "/" in name or name in {".", ".."}:
            raise InstalledWorkerError("PUBLICATION_NAME_INVALID")
        if (
            not isinstance(payload, bytes)
            or not payload
            or len(payload) > protocol.MAX_PAYLOAD_BYTES
        ):
            raise InstalledWorkerError("PUBLICATION_PAYLOAD_INVALID")
        parent = self._active_root.parent
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        active_fd = -1
        temp_name = f".{name}.tmp"
        temp_fd = -1
        try:
            parent_info = os.fstat(parent_fd)
            if (
                not stat.S_ISDIR(parent_info.st_mode)
                or parent_info.st_uid != 0
                or parent_info.st_mode & 0o022
            ):
                raise InstalledWorkerError("PUBLICATION_PARENT_UNPROTECTED")
            active_fd = os.open(
                self._active_root.name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            active_info = os.fstat(active_fd)
            if (
                not stat.S_ISDIR(active_info.st_mode)
                or active_info.st_uid != self._broker_uid
                or active_info.st_gid != self._broker_gid
                or stat.S_IMODE(active_info.st_mode) != 0o700
            ):
                raise InstalledWorkerError("PUBLICATION_ACTIVE_UNPROTECTED")
            temp_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=active_fd,
            )
            offset = 0
            while offset < len(payload):
                written = os.write(temp_fd, payload[offset:])
                if written <= 0:
                    raise InstalledWorkerError("PUBLICATION_ZERO_WRITE")
                offset += written
            os.fsync(temp_fd)
            temp_info = os.fstat(temp_fd)
            os.link(
                temp_name, name, src_dir_fd=active_fd, dst_dir_fd=active_fd, follow_symlinks=False
            )
            os.fsync(active_fd)
            os.unlink(temp_name, dir_fd=active_fd)
            os.fsync(active_fd)
            named_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=active_fd)
            try:
                named = os.fstat(named_fd)
                named_payload = _read_all(named_fd, named.st_size)
            finally:
                os.close(named_fd)
            current = os.stat(self._active_root.name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                (current.st_dev, current.st_ino) != (active_info.st_dev, active_info.st_ino)
                or (named.st_dev, named.st_ino) != (temp_info.st_dev, temp_info.st_ino)
                or not stat.S_ISREG(named.st_mode)
                or named.st_uid != self._broker_uid
                or named.st_gid != self._broker_gid
                or stat.S_IMODE(named.st_mode) != 0o600
                or named.st_nlink != 1
                or named.st_size != len(payload)
                or named_payload != payload
                or _sha256(named_payload) != _sha256(payload)
            ):
                raise InstalledWorkerError("PUBLICATION_IDENTITY_CHANGED")
            return {"sha256": _sha256(payload), "size": len(payload), "atomic": True}
        except FileExistsError as error:
            raise InstalledWorkerError("PUBLICATION_ALREADY_EXISTS") from error
        finally:
            if temp_fd >= 0:
                os.close(temp_fd)
            if active_fd >= 0:
                with suppress(FileNotFoundError):
                    os.unlink(temp_name, dir_fd=active_fd)
                os.close(active_fd)
            os.close(parent_fd)


def validate_fixture_registry(document: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    if not isinstance(document, Mapping) or set(document) != {"schema_version", "kind", "entries"}:
        raise InstalledWorkerError("FIXTURE_REGISTRY_INVALID")
    if (
        document["schema_version"] != FIXTURE_REGISTRY_VERSION
        or document["kind"] != FIXTURE_REGISTRY_KIND
    ):
        raise InstalledWorkerError("FIXTURE_REGISTRY_INVALID")
    entries = document["entries"]
    if not isinstance(entries, list) or not entries:
        raise InstalledWorkerError("FIXTURE_REGISTRY_INVALID")
    indexed: dict[str, Mapping[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {
            "task",
            "inputs",
            "oracle_request",
            "runtime_expectations",
        }:
            raise InstalledWorkerError("FIXTURE_REGISTRY_INVALID")
        task = entry["task"]
        inputs = entry["inputs"]
        oracle_request = entry["oracle_request"]
        runtime = entry["runtime_expectations"]
        if not isinstance(task, str) or not task or "/" in task or task in indexed:
            raise InstalledWorkerError("FIXTURE_REGISTRY_INVALID")
        if (
            not isinstance(inputs, Mapping)
            or not inputs
            or any(
                not isinstance(k, str) or not isinstance(v, str) or _DIGEST_RE.fullmatch(v) is None
                for k, v in inputs.items()
            )
        ):
            raise InstalledWorkerError("FIXTURE_REGISTRY_INVALID")
        if not isinstance(oracle_request, Mapping) or set(oracle_request) - {
            "schema_version",
            "source",
            "filename",
            "execution_mode",
            "endpoint",
            "metis_root",
            "metis_revision",
            "metis_tree",
            "workspace_sources",
        }:
            raise InstalledWorkerError("FIXTURE_REGISTRY_INVALID")
        if (
            oracle_request.get("schema_version") != 1
            or not isinstance(oracle_request.get("source"), str)
            or not oracle_request["source"]
            or not isinstance(oracle_request.get("filename"), str)
            or oracle_request.get("execution_mode") not in {"source", "endpoint"}
        ):
            raise InstalledWorkerError("FIXTURE_REGISTRY_INVALID")
        if "/Users/" in str(oracle_request) or _contains_path_escape(oracle_request):
            raise InstalledWorkerError("FIXTURE_REGISTRY_CALLER_PATH")
        if not isinstance(runtime, Mapping) or set(runtime) != RUNNER_RUNTIME_FIELDS:
            raise InstalledWorkerError("FIXTURE_REGISTRY_RUNTIME_INVALID")
        indexed[task] = entry
    return indexed


def _contains_path_escape(value: object) -> bool:
    if isinstance(value, str):
        return "\x00" in value or value.startswith("~")
    if isinstance(value, Mapping):
        return any(_contains_path_escape(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return any(_contains_path_escape(item) for item in value)
    return False


def _validate_runner_result(
    payload: bytes, runtime_expectations: Mapping[str, object]
) -> dict[str, object]:
    if not payload:
        raise InstalledWorkerError("RUNNER_OUTPUT_EMPTY")
    try:
        result = protocol.parse_canonical_json(payload)
    except protocol.BrokerProtocolError as error:
        raise InstalledWorkerError("RUNNER_OUTPUT_NOT_CANONICAL", str(error)) from error
    if not isinstance(result, dict) or set(result) != RUNNER_RESULT_FIELDS:
        raise InstalledWorkerError("RUNNER_OUTPUT_CONTRACT")
    if result["schema_version"] != 1 or result["status"] not in {"ok", "invalid"}:
        raise InstalledWorkerError("RUNNER_OUTPUT_CONTRACT")
    runtime = result.get("runtime")
    if (
        not isinstance(runtime, dict)
        or set(runtime) != RUNNER_RUNTIME_FIELDS
        or runtime != dict(runtime_expectations)
    ):
        raise InstalledWorkerError("RUNNER_RUNTIME_IDENTITY_MISMATCH")
    return result


class InstalledWorker:
    """Required payload/result adapter used by ``FixedLauncherTransport``."""

    def __init__(
        self,
        *,
        authority: Mapping[str, object],
        fixture_registry: Mapping[str, object],
        roster_probe: RosterProbe | None = None,
        publisher: PublicationWriter | None = None,
        publication_root: Path | None = None,
        identity_probe: Callable[[], tuple[int, int]] | None = None,
    ):
        try:
            self._authority = protocol.validate_authority(authority)
        except protocol.BrokerProtocolError as error:
            raise InstalledWorkerError("AUTHORITY_INVALID", str(error)) from error
        if self._authority["mode"] == protocol.MODE_PRODUCTION:
            raise InstalledWorkerError("PRODUCTION_MODE_FORBIDDEN")
        if self._authority["mode"] != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
            raise InstalledWorkerError("INSTALLED_MODE_INVALID")
        self._fixtures = validate_fixture_registry(fixture_registry)
        self._roster_probe = roster_probe or InstalledRosterProbe()
        if publisher is None:
            if publication_root is None:
                raise InstalledWorkerError("PUBLICATION_WRITER_REQUIRED")
            publisher = AtomicPublicationWriter(publication_root)
        self._publisher = publisher
        self._identity_probe = identity_probe or (lambda: (os.geteuid(), os.getegid()))

    def prepare(
        self,
        request: Mapping[str, object],
        authority: Mapping[str, object],
        _attempt: Mapping[str, object],
    ) -> service.PreparedLauncherPayload:
        if protocol.authority_hash(authority) != protocol.authority_hash(self._authority):
            raise InstalledWorkerError("AUTHORITY_CHANGED")
        payload = request.get("payload")
        if not isinstance(payload, Mapping) or set(payload) != {"task", "inputs"}:
            raise InstalledWorkerError("FIXTURE_SELECTOR_INVALID")
        task = payload.get("task")
        entry = self._fixtures.get(str(task))
        if entry is None or payload.get("inputs") != entry["inputs"]:
            raise InstalledWorkerError("FIXTURE_SELECTOR_NOT_REGISTERED")
        pre = self._roster_probe(self._authority)
        if pre != self._authority["installed_code_roster"]:
            raise InstalledWorkerError("PRE_ROSTER_INCOMPLETE")
        broker_uid, broker_gid = self._identity_probe()
        if type(broker_uid) is not int or type(broker_gid) is not int:
            raise InstalledWorkerError("BROKER_IDENTITY_UNAVAILABLE")
        oracle_request = dict(entry["oracle_request"])
        prepared = WorkerContext(
            pre_roster=tuple(dict(row) for row in pre),
            broker_uid=broker_uid,
            broker_gid=broker_gid,
            oracle_request=oracle_request,
        )
        return service.PreparedLauncherPayload(protocol.canonical_bytes(oracle_request), prepared)

    def finish(
        self,
        native: service.NativeLauncherResult,
        prepared: service.PreparedLauncherPayload,
        request: Mapping[str, object],
        authority: Mapping[str, object],
        attempt: Mapping[str, object],
    ) -> Mapping[str, object]:
        context = prepared.context
        if not isinstance(context, WorkerContext):
            raise InstalledWorkerError("WORKER_CONTEXT_INVALID")
        expected_broker = authority["broker_identity"]
        expected_runner = authority["runner_identity"]
        if (
            not native.child_boundary_succeeded
            or native.broker_peer_uid != context.broker_uid
            or native.broker_peer_gid != context.broker_gid
            or context.broker_uid != expected_broker["uid"]
            or context.broker_gid != expected_broker["gid"]
            or native.launcher_actual_uid != 0
            or native.launcher_actual_gid != 0
            or native.runner_target_uid != expected_runner["uid"]
            or native.runner_target_gid != expected_runner["gid"]
        ):
            raise InstalledWorkerError("NATIVE_IDENTITY_BOUNDARY_MISMATCH")
        if native.wait_kind != service.WAIT_EXITED or native.wait_value != 0:
            raise InstalledWorkerError("RUNNER_DID_NOT_COMPLETE")
        entry = self._fixtures[str(request["payload"]["task"])]
        _validate_runner_result(native.stdout, entry["runtime_expectations"])
        post = self._roster_probe(self._authority)
        pre = [dict(row) for row in context.pre_roster]
        if post != pre or post != authority["installed_code_roster"]:
            raise InstalledWorkerError("POST_ROSTER_CHANGED")
        publication_name = f"{attempt['attempt_sequence']}-{request['request_hash'][7:]}.json"
        publication = dict(self._publisher(publication_name, native.stdout))
        if publication != {
            "sha256": _sha256(native.stdout),
            "size": len(native.stdout),
            "atomic": True,
        }:
            raise InstalledWorkerError("PUBLICATION_BINDING_INVALID")
        installed = authority["installed_code_identity"]
        cleanup_sha256 = _sha256(native.cleanup_record)
        return {
            "measured": {
                "authority_sha256": protocol.authority_hash(authority),
                "release_sha256": authority["release_identity"]["ancestry_root_sha256"],
                "policy_sha256": authority["policy_identity"]["resolved_sha256"],
            },
            "identities": {
                "broker": {"user": "_metisbroker", "code_sha256": installed["broker_code_sha256"]},
                "launcher": {"code_sha256": installed["launcher_sha256"]},
                "worker": {"code_sha256": installed["worker_sha256"]},
                "node": {
                    "sha256": installed["node_sha256"],
                    "version": entry["runtime_expectations"]["node"],
                },
                "loader": {"sha256": installed["loader_sha256"]},
            },
            "effective_ids": {
                "broker_uid": native.broker_peer_uid,
                "broker_gid": native.broker_peer_gid,
                "runner_uid": native.runner_target_uid,
                "runner_gid": native.runner_target_gid,
                "launcher_uid": native.launcher_actual_uid,
                "launcher_gid": native.launcher_actual_gid,
            },
            "policy": dict(authority["policy_identity"]),
            "roster": {"pre": pre, "post": post},
            "output": {
                "stdout_sha256": _sha256(native.stdout),
                "stderr_sha256": _sha256(native.stderr),
                "exit_code": native.wait_value,
                "publication": publication,
            },
            "cleanup": {
                "process_census": {"residual_children": 0, "census_sha256": cleanup_sha256},
                "fd_census": {"retained_fds": 0, "census_sha256": cleanup_sha256},
                "temp_census": {"entries": [], "roster_sha256": cleanup_sha256},
            },
        }


class PublicReceiptJournal:
    """Append/replay exact signed receipt bytes; duplicate current tail is idempotent."""

    def __init__(
        self,
        path: Path,
        *,
        require_installed_metadata: bool = True,
        broker_uid: int = 499,
        consumer_gid: int = 20,
    ):
        if not isinstance(path, Path) or not path.is_absolute():
            raise InstalledWorkerError("PUBLIC_JOURNAL_PATH_INVALID")
        self._path = path
        self._require_installed_metadata = require_installed_metadata
        self._broker_uid = broker_uid
        self._consumer_gid = consumer_gid

    @staticmethod
    def _decode(payload: bytes) -> tuple[list[bytes], int, bool]:
        records: list[bytes] = []
        offset = 0
        while offset < len(payload):
            if len(payload) - offset < 4:
                return records, offset, True
            length = struct.unpack(">I", payload[offset : offset + 4])[0]
            record_start = offset
            offset += 4
            if length == 0 or length > PUBLIC_JOURNAL_MAX_RECORD_BYTES:
                raise InstalledWorkerError("PUBLIC_JOURNAL_CORRUPT")
            if len(payload) - offset < length:
                return records, record_start, True
            body = payload[offset : offset + length]
            offset += length
            try:
                receipt = protocol.parse_canonical_json(body)
                protocol.validate_receipt(receipt)
            except protocol.BrokerProtocolError as error:
                raise InstalledWorkerError("PUBLIC_JOURNAL_CORRUPT", str(error)) from error
            records.append(body)
            if len(records) > PUBLIC_JOURNAL_MAX_RECORDS:
                raise InstalledWorkerError("PUBLIC_JOURNAL_OVERSIZE")
        return records, offset, False

    def append(self, canonical_receipt: bytes) -> None:
        receipt = protocol.parse_canonical_json(canonical_receipt)
        validated = protocol.validate_receipt(receipt)
        if validated["mode"] != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
            raise InstalledWorkerError("PUBLIC_JOURNAL_MODE_INVALID")
        parent_fd = os.open(self._path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = -1
        try:
            parent_info = os.fstat(parent_fd)
            if self._require_installed_metadata and (
                parent_info.st_uid != 0 or parent_info.st_mode & 0o022
            ):
                raise InstalledWorkerError("PUBLIC_JOURNAL_PARENT_UNPROTECTED")
            fd = os.open(self._path.name, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW, dir_fd=parent_fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise InstalledWorkerError("PUBLIC_JOURNAL_LEAF_INVALID")
            if self._require_installed_metadata and (
                info.st_uid != self._broker_uid
                or info.st_gid != self._consumer_gid
                or stat.S_IMODE(info.st_mode) != 0o640
            ):
                raise InstalledWorkerError("PUBLIC_JOURNAL_LEAF_INVALID")
            fcntl.flock(fd, fcntl.LOCK_EX)
            locked_info = os.fstat(fd)
            named_info = os.stat(self._path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                (locked_info.st_dev, locked_info.st_ino) != (info.st_dev, info.st_ino)
                or (named_info.st_dev, named_info.st_ino) != (info.st_dev, info.st_ino)
                or locked_info.st_nlink != 1
                or (
                    self._require_installed_metadata
                    and (
                        locked_info.st_uid != self._broker_uid
                        or locked_info.st_gid != self._consumer_gid
                        or stat.S_IMODE(locked_info.st_mode) != 0o640
                    )
                )
            ):
                raise InstalledWorkerError("PUBLIC_JOURNAL_IDENTITY_CHANGED")
            os.lseek(fd, 0, os.SEEK_SET)
            payload = _read_all(fd, locked_info.st_size)
            records, valid_offset, torn = self._decode(payload)
            sequence = int(validated["receipt_sequence"])
            if records:
                tail = protocol.parse_canonical_json(records[-1])
                tail_sequence = int(tail["receipt_sequence"])
                if sequence == tail_sequence and canonical_receipt == records[-1]:
                    return
                if sequence != tail_sequence + 1 or validated[
                    "previous_receipt_sha256"
                ] != protocol.receipt_hash(tail):
                    raise InstalledWorkerError("PUBLIC_JOURNAL_CHAIN_MISMATCH")
            elif (
                sequence != 1
                or validated["previous_receipt_sha256"] != protocol.GENESIS_RECEIPT_DIGEST
            ):
                raise InstalledWorkerError("PUBLIC_JOURNAL_GENESIS_MISMATCH")
            if torn:
                # The incoming receipt came from the already-fsynced broker
                # ledger.  Only that exact next chain position authorizes
                # truncating an unambiguous partial journal tail.
                os.ftruncate(fd, valid_offset)
                os.fsync(fd)
            encoded = struct.pack(">I", len(canonical_receipt)) + canonical_receipt
            if valid_offset + len(encoded) > PUBLIC_JOURNAL_MAX_BYTES:
                raise InstalledWorkerError("PUBLIC_JOURNAL_OVERSIZE")
            written = 0
            while written < len(encoded):
                count = os.write(fd, encoded[written:])
                if count <= 0:
                    raise InstalledWorkerError("PUBLIC_JOURNAL_ZERO_WRITE")
                written += count
            os.fsync(fd)
            os.fsync(parent_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            os.close(parent_fd)


class JournaledBrokerCore:
    """Publish the ledger-backed exact receipt to the public journal before delivery."""

    def __init__(self, broker: object, journal: PublicReceiptJournal):
        handle = getattr(broker, "handle", None)
        if not callable(handle):
            raise InstalledWorkerError("BROKER_CORE_INVALID")
        self._broker = broker
        self._journal = journal

    def handle(self, canonical_request: bytes) -> bytes:
        response = self._broker.handle(canonical_request)
        if not isinstance(response, bytes):
            raise InstalledWorkerError("BROKER_RESPONSE_INVALID")
        self._journal.append(response)
        return response


__all__ = [
    "AtomicPublicationWriter",
    "InstalledRosterProbe",
    "InstalledWorker",
    "InstalledWorkerError",
    "JournaledBrokerCore",
    "PublicReceiptJournal",
    "WorkerContext",
    "validate_fixture_registry",
]
