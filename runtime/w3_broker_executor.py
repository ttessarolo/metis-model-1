#!/usr/bin/env python3
"""Installed broker factory plus default-dry transactional install executor.

The broker factory only reads an already provisioned seed.  The private macOS
installer path may create the protected-public-synthetic seed, but only after
root, exact plan and exact raw bundle consent gates are satisfied.
"""

from __future__ import annotations

import argparse
import fcntl
import grp
import hashlib
import json
import os
import pwd
import re
import stat
import struct
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from metis_model1 import w3_broker_client as broker_client
from runtime import w3_anchor_service as anchor_service
from runtime import w3_broker_installer as installer
from runtime import w3_broker_protocol as protocol
from runtime import w3_broker_service as service
from runtime import w3_installed_worker as worker_module
from runtime import w3_protected_broker as broker_core

CONFIG_KIND = "w3-protected-broker-installed-config"
CONFIG_VERSION = 1
PUBLIC_KEY_REGISTRY_KIND = "w3-protected-public-key-registry"
INSTALL_JOURNAL_KIND = "w3-phase-b-install-transition"
INSTALL_JOURNAL_DOMAIN = "w3-phase-b-install-transition/v1"
INSTALL_JOURNAL_GENESIS = protocol.SHA256_PREFIX + "0" * 64
INSTALL_JOURNAL_MAX_RECORD = 1024 * 1024
INSTALL_JOURNAL_MAX_BYTES = 64 * 1024 * 1024
INSTALL_JOURNAL_MAX_RECORDS = 65_536
STAGED_PLAN_PATH = Path(installer.STAGED_BUNDLE_ROOT) / "metadata" / "install-plan.json"
STAGED_MANIFEST_PATH = (
    Path(installer.STAGED_BUNDLE_ROOT) / "metadata" / "w3-phase-b-install-bundle.json"
)
INSTALL_BUNDLE_MAX_BYTES = 64 * 1024 * 1024
_CONFIG_FIELDS = {
    "schema_version",
    "kind",
    "mode",
    "authority_path",
    "public_key_registry_path",
    "fixture_registry_path",
    "private_key_path",
    "ledger_path",
    "public_receipt_journal_path",
    "publication_root",
    "installed_roster_path_map",
    "max_inflight",
}
_EXPECTED_PATHS = {
    "authority_path": Path(installer.AUTHORITY_REGISTRY_PATH),
    "public_key_registry_path": Path(installer.PUBLIC_KEY_REGISTRY_PATH),
    "fixture_registry_path": Path(installer.PUBLIC_FIXTURE_REGISTRY_PATH),
    "private_key_path": Path(installer.SIGNING_KEY_PATH),
    "ledger_path": Path(installer.BROKER_LEDGER_PATH),
    "public_receipt_journal_path": Path(installer.PUBLIC_RECEIPT_JOURNAL_PATH),
    "publication_root": Path(installer.PUBLICATION_ACTIVE),
}


class BrokerExecutorError(RuntimeError):
    """Stable fail-closed error for factory or install execution."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


def _is_sha256_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


@dataclass(frozen=True)
class FilePolicy:
    owner_uid: int
    owner_gid: int | None
    mode: int
    parent_root_owned: bool = True


class SecureReader(Protocol):
    def __call__(self, path: Path, policy: FilePolicy) -> bytes: ...


def _path_parts(path: Path) -> tuple[str, ...]:
    if not path.is_absolute() or "/Users/" in str(path):
        raise BrokerExecutorError("INSTALLED_PATH_INVALID", str(path))
    parts = PurePosixPath(str(path)).parts[1:]
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise BrokerExecutorError("INSTALLED_PATH_INVALID", str(path))
    return tuple(parts)


def secure_read(
    path: Path, policy: FilePolicy, *, max_bytes: int = protocol.MAX_PAYLOAD_BYTES
) -> bytes:
    """Read one exact leaf through root-owned O_NOFOLLOW ancestry."""

    parts = _path_parts(path)
    parent_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            info = os.fstat(next_fd)
            if not stat.S_ISDIR(info.st_mode) or (
                policy.parent_root_owned and (info.st_uid != 0 or info.st_mode & 0o022)
            ):
                os.close(next_fd)
                raise BrokerExecutorError("INSTALLED_PARENT_UNPROTECTED", str(path))
            os.close(parent_fd)
            parent_fd = next_fd
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != policy.owner_uid
                or (policy.owner_gid is not None and info.st_gid != policy.owner_gid)
                or stat.S_IMODE(info.st_mode) != policy.mode
            ):
                raise BrokerExecutorError("INSTALLED_LEAF_UNPROTECTED", str(path))
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise BrokerExecutorError("INSTALLED_LEAF_OVERSIZE", str(path))
            return b"".join(chunks)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def _canonical_document(payload: bytes, label: str) -> dict[str, object]:
    try:
        value = protocol.parse_canonical_json(payload)
    except protocol.BrokerProtocolError as error:
        raise BrokerExecutorError(f"{label}_INVALID", str(error)) from error
    if not isinstance(value, dict):
        raise BrokerExecutorError(f"{label}_INVALID")
    return value


def _validate_config(document: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(document, Mapping) or set(document) != _CONFIG_FIELDS:
        raise BrokerExecutorError("BROKER_CONFIG_INVALID")
    config = dict(document)
    if config["schema_version"] != CONFIG_VERSION or config["kind"] != CONFIG_KIND:
        raise BrokerExecutorError("BROKER_CONFIG_INVALID")
    if config["mode"] == protocol.MODE_PRODUCTION:
        raise BrokerExecutorError("PRODUCTION_MODE_FORBIDDEN")
    if config["mode"] != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
        raise BrokerExecutorError("BROKER_CONFIG_MODE_INVALID")
    for field, expected in _EXPECTED_PATHS.items():
        if config[field] != str(expected):
            raise BrokerExecutorError("BROKER_CONFIG_PATH_NOT_FIXED", field)
    max_inflight = config["max_inflight"]
    if type(max_inflight) is not int or max_inflight != 1:
        raise BrokerExecutorError("BROKER_CONFIG_QUEUE_INVALID")
    path_map = config["installed_roster_path_map"]
    if not isinstance(path_map, dict) or not path_map:
        raise BrokerExecutorError("BROKER_CONFIG_ROSTER_PATH_MAP_INVALID")
    for logical, installed in path_map.items():
        if (
            not isinstance(logical, str)
            or not isinstance(installed, str)
            or not installed.startswith("/")
            or "/Users/" in installed
            or "\x00" in installed
        ):
            raise BrokerExecutorError("BROKER_CONFIG_ROSTER_PATH_MAP_INVALID")
    if list(path_map) != sorted(path_map) or len(set(path_map.values())) != len(path_map):
        raise BrokerExecutorError("BROKER_CONFIG_ROSTER_PATH_MAP_INVALID")
    return config


def _verification_registry(document: Mapping[str, object]) -> dict[str, bytes]:
    if not isinstance(document, Mapping) or set(document) != {"schema_version", "kind", "keys"}:
        raise BrokerExecutorError("PUBLIC_KEY_REGISTRY_INVALID")
    if document["schema_version"] != 1 or document["kind"] != PUBLIC_KEY_REGISTRY_KIND:
        raise BrokerExecutorError("PUBLIC_KEY_REGISTRY_INVALID")
    keys = document["keys"]
    if not isinstance(keys, list) or not keys:
        raise BrokerExecutorError("PUBLIC_KEY_REGISTRY_INVALID")
    result: dict[str, bytes] = {}
    for row in keys:
        if not isinstance(row, Mapping) or set(row) != {
            "mode",
            "algorithm",
            "key_id",
            "public_key",
        }:
            raise BrokerExecutorError("PUBLIC_KEY_REGISTRY_INVALID")
        if (
            row["mode"] != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC
            or row["algorithm"] != protocol.PRODUCTION_ALGORITHM
        ):
            raise BrokerExecutorError("PUBLIC_KEY_REGISTRY_INVALID")
        try:
            public_key = protocol.ed25519.decode_public_key(row["public_key"])
            expected = protocol.ed25519.mode_scoped_key_id(
                public_key, mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC
            )
        except protocol.ed25519.Ed25519ContractError as error:
            raise BrokerExecutorError("PUBLIC_KEY_REGISTRY_INVALID", error.reason) from error
        key_id = row["key_id"]
        if key_id != expected or not isinstance(key_id, str) or key_id in result:
            raise BrokerExecutorError("PUBLIC_KEY_REGISTRY_INVALID")
        result[key_id] = public_key
    return result


def _protected_signer(
    seed: bytes, expected_key_id: str
) -> Callable[[Mapping[str, object]], Mapping[str, object]]:
    try:
        public_key = protocol.ed25519.derive_public_key(seed)
        derived = protocol.ed25519.mode_scoped_key_id(
            public_key, mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC
        )
    except protocol.ed25519.Ed25519ContractError as error:
        raise BrokerExecutorError("PRIVATE_KEY_INVALID", error.reason) from error
    if derived != expected_key_id:
        raise BrokerExecutorError("PRIVATE_KEY_AUTHORITY_MISMATCH")

    def sign(receipt: Mapping[str, object]) -> Mapping[str, object]:
        return protocol.attach_protected_public_synthetic_signature(
            receipt,
            private_key=seed,
            registered_key_id=expected_key_id,
        )

    return sign


def build_installed_broker(
    config_path: Path = Path(installer.BROKER_CONFIG_PATH),
    *,
    reader: SecureReader = secure_read,
    connector: service.LauncherConnector | None = None,
    roster_probe: worker_module.RosterProbe | None = None,
    publisher: worker_module.PublicationWriter | None = None,
    identity_probe: Callable[[], tuple[int, int]] | None = None,
    journal_factory: Callable[[Path], worker_module.PublicReceiptJournal] | None = None,
) -> worker_module.JournaledBrokerCore:
    """Construct the installed broker from fixed, separately protected leaves."""

    if config_path != Path(installer.BROKER_CONFIG_PATH):
        raise BrokerExecutorError("BROKER_CONFIG_PATH_NOT_FIXED")
    config = _validate_config(
        _canonical_document(
            reader(config_path, FilePolicy(0, installer.BROKER_GID, 0o440)), "BROKER_CONFIG"
        )
    )
    authority = _canonical_document(
        reader(Path(str(config["authority_path"])), FilePolicy(0, 0, 0o444)), "AUTHORITY"
    )
    try:
        authority = protocol.validate_authority(authority)
    except protocol.BrokerProtocolError as error:
        raise BrokerExecutorError("AUTHORITY_INVALID", str(error)) from error
    # This rejection deliberately precedes the private-key read.
    if authority["mode"] == protocol.MODE_PRODUCTION:
        raise BrokerExecutorError("PRODUCTION_MODE_FORBIDDEN")
    if (
        authority["mode"] != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC
        or authority["broker_identity"]
        != {
            "user": installer.BROKER_PRINCIPAL,
            "uid": installer.BROKER_UID,
            "gid": installer.BROKER_GID,
        }
        or authority["runner_identity"]
        != {
            "user": installer.RUNNER_PRINCIPAL,
            "uid": installer.RUNNER_UID,
            "gid": installer.RUNNER_GID,
        }
    ):
        raise BrokerExecutorError("AUTHORITY_INSTALLED_IDENTITY_MISMATCH")
    path_map = dict(config["installed_roster_path_map"])
    authority_paths = {str(row["path"]) for row in authority["installed_code_roster"]}
    if set(path_map) != authority_paths:
        raise BrokerExecutorError("AUTHORITY_INSTALLED_ROSTER_PATH_MAP_MISMATCH")
    for role, logical in authority["installed_code_paths"].items():
        if path_map.get(str(logical)) != installer.EXPECTED_ARTIFACT_PATHS[str(role)]:
            raise BrokerExecutorError("AUTHORITY_INSTALLED_ROSTER_PATH_MAP_MISMATCH")
    public_registry = _verification_registry(
        _canonical_document(
            reader(Path(str(config["public_key_registry_path"])), FilePolicy(0, 0, 0o444)),
            "PUBLIC_KEY_REGISTRY",
        )
    )
    fixture_registry = _canonical_document(
        reader(Path(str(config["fixture_registry_path"])), FilePolicy(0, 0, 0o444)),
        "FIXTURE_REGISTRY",
    )
    seed = reader(Path(str(config["private_key_path"])), FilePolicy(0, installer.BROKER_GID, 0o440))
    if len(seed) != protocol.ed25519.PRIVATE_KEY_BYTES:
        raise BrokerExecutorError("PRIVATE_KEY_INVALID")
    signer = _protected_signer(seed, str(authority["signing"]["key_id"]))
    if roster_probe is None:
        roster_probe = worker_module.InstalledRosterProbe(
            path_map={logical: Path(path) for logical, path in path_map.items()}
        )
    installed_worker = worker_module.InstalledWorker(
        authority=authority,
        fixture_registry=fixture_registry,
        roster_probe=roster_probe,
        publisher=publisher,
        publication_root=Path(str(config["publication_root"])),
        identity_probe=identity_probe,
    )
    transport = service.FixedLauncherTransport(
        payload_adapter=installed_worker.prepare,
        result_adapter=installed_worker.finish,
        connector=connector,
    )
    core = broker_core.ProtectedExecutionBroker(
        authority=authority,
        ledger_path=Path(str(config["ledger_path"])),
        executor=transport,
        protected_signer=signer,
        verification_keys=public_registry,
        max_inflight=int(config["max_inflight"]),
        require_existing_ledger=True,
        allow_unprotected_test_ledger=False,
    )
    factory = journal_factory or (lambda path: worker_module.PublicReceiptJournal(path))
    return worker_module.JournaledBrokerCore(
        core, factory(Path(str(config["public_receipt_journal_path"])))
    )


# ---------------------------------------------------------------------------
# Transactional default-dry install-plan executor.
# ---------------------------------------------------------------------------


class InstallerBackend(Protocol):
    operation_roster_sha256: str
    simulation: bool

    def apply(self, step: Mapping[str, object]) -> object: ...
    def rollback(self, rollback_id: str, details: Mapping[str, object]) -> int: ...


class TransitionJournal(Protocol):
    def append(self, record: Mapping[str, object]) -> None: ...
    def records(self, *, repair_torn_tail: bool = False) -> list[dict[str, object]]: ...
    def session(self): ...


@dataclass(frozen=True)
class BackendEffect:
    count: int
    ownership_receipt: Mapping[str, object] | None = None


@dataclass(frozen=True)
class OperationReconciliation:
    """Typed recovery result for one durably-started apply operation."""

    status: str
    ownership_receipt: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.status not in {"not-applied", "owned-applied", "cleaned"}:
            raise BrokerExecutorError("INSTALL_OPERATION_RECONCILIATION_INVALID")
        if self.status == "owned-applied" and not isinstance(self.ownership_receipt, Mapping):
            raise BrokerExecutorError("INSTALL_OPERATION_RECONCILIATION_INVALID")
        if self.status != "owned-applied" and self.ownership_receipt is not None:
            raise BrokerExecutorError("INSTALL_OPERATION_RECONCILIATION_INVALID")


def _normalize_backend_effect(value: object, step_id: str) -> BackendEffect:
    if isinstance(value, BackendEffect):
        result = value
    elif type(value) is int:
        # Test/simulation backends may return a count, but cannot authorize
        # destructive rollback without a durable ownership receipt.
        result = BackendEffect(int(value), None)
    else:
        raise BrokerExecutorError("INSTALL_STEP_EFFECT_RESULT_INVALID", step_id)
    if type(result.count) is not int or result.count < 1:
        raise BrokerExecutorError("INSTALL_STEP_EFFECT_RESULT_INVALID", step_id)
    if result.ownership_receipt is not None and not isinstance(result.ownership_receipt, Mapping):
        raise BrokerExecutorError("INSTALL_STEP_OWNERSHIP_RECEIPT_INVALID", step_id)
    return result


def _transition_material(
    sequence: int, previous: str, payload: Mapping[str, object]
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": INSTALL_JOURNAL_KIND,
        "record_sequence": sequence,
        "previous_record_sha256": previous,
        "payload": dict(payload),
    }


def _decode_transition_records(raw: bytes) -> tuple[list[dict[str, object]], int, bool]:
    records: list[dict[str, object]] = []
    offset = 0
    previous = INSTALL_JOURNAL_GENESIS
    while offset < len(raw):
        record_start = offset
        if len(raw) - offset < 4:
            return records, record_start, True
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        offset += 4
        if length == 0 or length > INSTALL_JOURNAL_MAX_RECORD:
            raise BrokerExecutorError("INSTALL_JOURNAL_CORRUPT", "record length")
        if len(raw) - offset < length:
            # append() fsyncs the complete record before returning.  An
            # incomplete final body cannot authorize its following host effect.
            return records, record_start, True
        body = raw[offset : offset + length]
        offset += length
        try:
            decoded = protocol.parse_canonical_json(body)
        except protocol.BrokerProtocolError as error:
            raise BrokerExecutorError("INSTALL_JOURNAL_CORRUPT", str(error)) from error
        if not isinstance(decoded, dict) or set(decoded) != {
            "schema_version",
            "kind",
            "record_sequence",
            "previous_record_sha256",
            "payload",
            "record_sha256",
        }:
            raise BrokerExecutorError("INSTALL_JOURNAL_CORRUPT", "record fields")
        sequence = len(records) + 1
        if (
            decoded["schema_version"] != 1
            or decoded["kind"] != INSTALL_JOURNAL_KIND
            or decoded["record_sequence"] != sequence
            or decoded["previous_record_sha256"] != previous
            or not isinstance(decoded["payload"], dict)
        ):
            raise BrokerExecutorError("INSTALL_JOURNAL_CORRUPT", "record chain")
        material = _transition_material(sequence, previous, decoded["payload"])
        expected_hash = protocol.domain_digest(INSTALL_JOURNAL_DOMAIN, material)
        if decoded["record_sha256"] != expected_hash:
            raise BrokerExecutorError("INSTALL_JOURNAL_CORRUPT", "record hash")
        records.append(decoded)
        previous = expected_hash
        if len(records) > INSTALL_JOURNAL_MAX_RECORDS:
            raise BrokerExecutorError("INSTALL_JOURNAL_OVERSIZE")
    return records, offset, False


class FileTransitionJournal:
    """Canonical, length-prefixed fsynced transition journal on a precreated leaf."""

    def __init__(self, path: Path, *, require_root: bool = True):
        if not isinstance(path, Path) or not path.is_absolute():
            raise BrokerExecutorError("INSTALL_JOURNAL_PATH_INVALID")
        self._path = path
        self._require_root = require_root

    @property
    def path(self) -> Path:
        return self._path

    def _bootstrap_parent(self) -> None:
        if self._path != Path(installer.INSTALL_TRANSITION_JOURNAL_PATH) or not self._require_root:
            raise BrokerExecutorError("INSTALL_JOURNAL_BOOTSTRAP_PATH_INVALID")
        parent_fd = os.open(self._path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parent_info = os.fstat(parent_fd)
            if parent_info.st_uid != 0 or parent_info.st_gid != 0 or parent_info.st_mode & 0o022:
                raise BrokerExecutorError("INSTALL_JOURNAL_BOOTSTRAP_ANCESTRY_UNPROTECTED")
        finally:
            os.close(parent_fd)

    @contextmanager
    def _locked(self, *, bootstrap: bool = False):
        if bootstrap:
            self._bootstrap_parent()
        parent_fd = os.open(self._path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = -1
        try:
            parent_info = os.fstat(parent_fd)
            if self._require_root and (
                parent_info.st_uid != 0
                or parent_info.st_gid != 0
                or stat.S_IMODE(parent_info.st_mode) != 0o700
            ):
                raise BrokerExecutorError("INSTALL_JOURNAL_PARENT_UNPROTECTED")
            try:
                fd = os.open(
                    self._path.name, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW, dir_fd=parent_fd
                )
            except FileNotFoundError:
                if not bootstrap:
                    raise
                try:
                    fd = os.open(
                        self._path.name,
                        os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=parent_fd,
                    )
                except FileExistsError:
                    fd = os.open(
                        self._path.name, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW, dir_fd=parent_fd
                    )
                else:
                    os.fchown(fd, 0, 0)
                    os.fchmod(fd, 0o600)
                    os.fsync(fd)
                    os.fsync(parent_fd)
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise BrokerExecutorError("INSTALL_JOURNAL_LEAF_INVALID")
            fcntl.flock(fd, fcntl.LOCK_EX)
            locked = os.fstat(fd)
            named = os.stat(self._path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                (locked.st_dev, locked.st_ino) != (opened.st_dev, opened.st_ino)
                or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
                or locked.st_nlink != 1
                or locked.st_size > INSTALL_JOURNAL_MAX_BYTES
                or (
                    self._require_root
                    and (
                        locked.st_uid != 0
                        or locked.st_gid != 0
                        or stat.S_IMODE(locked.st_mode) != 0o600
                    )
                )
            ):
                raise BrokerExecutorError("INSTALL_JOURNAL_IDENTITY_CHANGED")
            yield fd, parent_fd, locked
        finally:
            if fd >= 0:
                os.close(fd)
            os.close(parent_fd)

    @staticmethod
    def _read(fd: int, size: int) -> bytes:
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                raise BrokerExecutorError("INSTALL_JOURNAL_SIZE_CHANGED")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise BrokerExecutorError("INSTALL_JOURNAL_SIZE_CHANGED")
        return b"".join(chunks)

    def _snapshot(self, fd: int, parent_fd: int) -> os.stat_result:
        locked = os.fstat(fd)
        named = os.stat(self._path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            (named.st_dev, named.st_ino) != (locked.st_dev, locked.st_ino)
            or locked.st_nlink != 1
            or locked.st_size > INSTALL_JOURNAL_MAX_BYTES
            or (
                self._require_root
                and (
                    locked.st_uid != 0
                    or locked.st_gid != 0
                    or stat.S_IMODE(locked.st_mode) != 0o600
                )
            )
        ):
            raise BrokerExecutorError("INSTALL_JOURNAL_IDENTITY_CHANGED")
        return locked

    def _records_locked(
        self, fd: int, parent_fd: int, *, repair_torn_tail: bool
    ) -> list[dict[str, object]]:
        locked = self._snapshot(fd, parent_fd)
        raw = self._read(fd, locked.st_size)
        records, valid_offset, torn = _decode_transition_records(raw)
        if torn:
            if not repair_torn_tail:
                raise BrokerExecutorError("INSTALL_JOURNAL_TORN_PREFIX")
            os.ftruncate(fd, valid_offset)
            os.fsync(fd)
            os.fsync(parent_fd)
        return records

    def _append_locked(self, fd: int, parent_fd: int, record: Mapping[str, object]) -> None:
        fields = {
            "schema_version",
            "kind",
            "transaction_id",
            "event",
            "plan_sha256",
            "bundle_sha256",
            "bundle_file_sha256",
            "step_id",
            "operation_id",
            "operation_intent",
            "ownership_receipt",
        }
        if (
            not isinstance(record, Mapping)
            or set(record) != fields
            or record["schema_version"] != 1
            or record["kind"] != INSTALL_JOURNAL_KIND
            or type(record["transaction_id"]) is not int
            or int(record["transaction_id"]) < 1
        ):
            raise BrokerExecutorError("INSTALL_JOURNAL_PAYLOAD_INVALID")
        ownership = record["ownership_receipt"]
        intent = record["operation_intent"]
        if (ownership is not None and not isinstance(ownership, Mapping)) or (
            intent is not None and not isinstance(intent, Mapping)
        ):
            raise BrokerExecutorError("INSTALL_JOURNAL_PAYLOAD_INVALID")
        payload = {
            "transaction_id": record["transaction_id"],
            "event": record["event"],
            "plan_sha256": record["plan_sha256"],
            "bundle_sha256": record["bundle_sha256"],
            "bundle_file_sha256": record["bundle_file_sha256"],
            "step_id": record["step_id"],
            "operation_id": record["operation_id"],
            "operation_intent": None if intent is None else dict(intent),
            "ownership_receipt": None if ownership is None else dict(ownership),
        }
        locked = self._snapshot(fd, parent_fd)
        raw = self._read(fd, locked.st_size)
        records, valid_offset, torn = _decode_transition_records(raw)
        if torn:
            os.ftruncate(fd, valid_offset)
            os.fsync(fd)
        previous = records[-1]["record_sha256"] if records else INSTALL_JOURNAL_GENESIS
        material = _transition_material(len(records) + 1, str(previous), payload)
        document = {
            **material,
            "record_sha256": protocol.domain_digest(INSTALL_JOURNAL_DOMAIN, material),
        }
        body = protocol.canonical_bytes(document)
        if len(body) > INSTALL_JOURNAL_MAX_RECORD:
            raise BrokerExecutorError("INSTALL_JOURNAL_RECORD_OVERSIZE")
        encoded = struct.pack(">I", len(body)) + body
        if valid_offset + len(encoded) > INSTALL_JOURNAL_MAX_BYTES:
            raise BrokerExecutorError("INSTALL_JOURNAL_OVERSIZE")
        offset = 0
        while offset < len(encoded):
            count = os.write(fd, encoded[offset:])
            if count <= 0:
                raise BrokerExecutorError("INSTALL_JOURNAL_ZERO_WRITE")
            offset += count
        os.fsync(fd)
        os.fsync(parent_fd)

    @contextmanager
    def session(self):
        """Hold one inode-bound exclusive flock across recovery and all effects."""

        with self._locked() as (fd, parent_fd, _locked):
            yield _FileTransitionSession(self, fd, parent_fd)

    @contextmanager
    def bootstrap_session(self):
        """Create only the fixed root journal precondition and retain its lock."""

        with self._locked(bootstrap=True) as (fd, parent_fd, _locked):
            yield _FileTransitionSession(self, fd, parent_fd)

    def records(self, *, repair_torn_tail: bool = False) -> list[dict[str, object]]:
        with self.session() as session:
            return session.records(repair_torn_tail=repair_torn_tail)

    def append(self, record: Mapping[str, object]) -> None:
        with self.session() as session:
            session.append(record)


class _FileTransitionSession:
    def __init__(self, owner: FileTransitionJournal, fd: int, parent_fd: int):
        self._owner = owner
        self._fd = fd
        self._parent_fd = parent_fd

    @contextmanager
    def session(self):
        yield self

    def records(self, *, repair_torn_tail: bool = False) -> list[dict[str, object]]:
        return self._owner._records_locked(
            self._fd, self._parent_fd, repair_torn_tail=repair_torn_tail
        )

    def append(self, record: Mapping[str, object]) -> None:
        self._owner._append_locked(self._fd, self._parent_fd, record)


class StructuredArgvBackend:
    """Run only frozen argv vectors through an injected non-shell runner."""

    ALLOWED_EXECUTABLES = frozenset(
        {
            "/usr/bin/dscl",
            "/usr/bin/dseditgroup",
            "/bin/mkdir",
            "/bin/chmod",
            "/usr/sbin/chown",
            "/bin/cp",
            "/bin/mv",
            "/bin/launchctl",
        }
    )

    def __init__(
        self,
        commands: Mapping[str, Sequence[Sequence[str]]],
        rollback_commands: Mapping[str, Sequence[Sequence[str]]],
        runner: Callable[[tuple[str, ...]], None],
    ):
        self._commands = self._freeze(commands)
        self._rollback = self._freeze(rollback_commands)
        if set(self._commands) != set(installer.INSTALL_STEP_IDS) or any(
            len(self._commands[step]) != len(installer.MACOS_BACKEND_OPERATION_ROSTER[step])
            for step in installer.INSTALL_STEP_IDS
        ):
            raise BrokerExecutorError("SIMULATION_BACKEND_ROSTER_INCOMPLETE")
        if set(self._rollback) != set(installer.ROLLBACK_STEP_IDS) or any(
            not self._rollback[step] for step in installer.ROLLBACK_STEP_IDS
        ):
            raise BrokerExecutorError("SIMULATION_ROLLBACK_ROSTER_INCOMPLETE")
        self._runner = runner
        self.operation_roster_sha256 = installer.backend_roster_digest()
        self.simulation = True

    @classmethod
    def _freeze(
        cls, commands: Mapping[str, Sequence[Sequence[str]]]
    ) -> dict[str, tuple[tuple[str, ...], ...]]:
        frozen: dict[str, tuple[tuple[str, ...], ...]] = {}
        for key, vectors in commands.items():
            rows: list[tuple[str, ...]] = []
            for vector in vectors:
                argv = tuple(vector)
                if (
                    not argv
                    or argv[0] not in cls.ALLOWED_EXECUTABLES
                    or any(
                        not isinstance(item, str) or "\x00" in item or item in {"sh", "-c"}
                        for item in argv
                    )
                ):
                    raise BrokerExecutorError("INSTALL_ARGV_NOT_ALLOWED", str(key))
                rows.append(argv)
            frozen[str(key)] = tuple(rows)
        return frozen

    def apply(self, step: Mapping[str, object]) -> int:
        vectors = self._commands.get(str(step["id"]), ())
        for argv in vectors:
            self._runner(argv)
        return len(vectors)

    def rollback(self, rollback_id: str, _details: Mapping[str, object]) -> int:
        vectors = self._rollback.get(rollback_id, ())
        for argv in vectors:
            self._runner(argv)
        return len(vectors)


class MacOSInstallBackend:
    """Fixed macOS implementation.  No command or path is caller supplied."""

    simulation = False
    _ENV = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    _LAUNCHD_POLL_ATTEMPTS = 50
    _LAUNCHD_POLL_INTERVAL_SECONDS = 0.1
    _LAUNCHD_BOOTSTRAP_OPERATIONS = {
        "launchctl-bootstrap-launcher": (
            installer.LAUNCHER_PLIST_LABEL,
            installer.EXPECTED_ARTIFACT_PATHS["launcher-plist"],
        ),
        "launchctl-bootstrap-anchor": (
            installer.ANCHOR_PLIST_LABEL,
            installer.EXPECTED_ARTIFACT_PATHS["anchor-plist"],
        ),
        "launchctl-bootstrap-broker": (
            installer.BROKER_PLIST_LABEL,
            installer.EXPECTED_ARTIFACT_PATHS["broker-plist"],
        ),
    }
    _LAUNCHD_KICKSTART_OPERATIONS = {
        "launchctl-kickstart-launcher-after-authority": (
            installer.LAUNCHER_PLIST_LABEL,
            installer.EXPECTED_ARTIFACT_PATHS["launcher-plist"],
        ),
        "launchctl-kickstart-anchor-after-authority": (
            installer.ANCHOR_PLIST_LABEL,
            installer.EXPECTED_ARTIFACT_PATHS["anchor-plist"],
        ),
        "launchctl-kickstart-broker-after-authority": (
            installer.BROKER_PLIST_LABEL,
            installer.EXPECTED_ARTIFACT_PATHS["broker-plist"],
        ),
    }
    _POLICY_TEMPLATE_SHA256 = (
        "sha256:4f29bf5e092d83993f19ad3d257cafd968a69b708679cecf5edc03cdf018de51"
    )
    _MUTABLE_RECEIPT_PATHS = frozenset(
        {
            installer.INSTALL_TRANSITION_JOURNAL_PATH,
            installer.BROKER_LEDGER_PATH,
            installer.PUBLIC_RECEIPT_JOURNAL_PATH,
            installer.ANCHOR_LOG_PATH,
        }
    )

    def __init__(self, bundle_manifest: Mapping[str, object]):
        try:
            self._bundle = installer.validate_bundle_manifest(bundle_manifest, require_frozen=True)
        except installer.InstallerError as error:
            raise BrokerExecutorError("MACOS_BACKEND_BUNDLE_INVALID", str(error)) from error
        self.operation_roster_sha256 = installer.backend_roster_digest()
        self._artifacts = {str(row["role"]): dict(row) for row in self._bundle["artifacts"]}
        self._source_rows = {
            str(row["path"]): dict(row) for row in self._bundle["source_roster"]["entries"]
        }
        self._install_rows = {
            str(row["path"]): dict(row) for row in self._bundle["install_roster"]["entries"]
        }
        self._directories = {
            str(row["path"]): (int(row["uid"]), int(row["gid"]), int(row["mode"]))
            for row in self._bundle["directories"]
        }
        self._applied_evidence: dict[str, object] | None = None
        self._pending_operation_intents: dict[tuple[str, str], Mapping[str, object] | None] = {}
        supported = set().union(*installer.MACOS_BACKEND_OPERATION_ROSTER.values())
        if supported != self._supported_operations():
            raise BrokerExecutorError("MACOS_BACKEND_OPERATION_IMPLEMENTATION_DRIFT")

    @property
    def applied_evidence(self) -> Mapping[str, object] | None:
        return None if self._applied_evidence is None else dict(self._applied_evidence)

    @property
    def bundle_sha256(self) -> str:
        return str(self._bundle["bundle_sha256"])

    @staticmethod
    def _supported_operations() -> set[str]:
        return {
            operation
            for operations in installer.MACOS_BACKEND_OPERATION_ROSTER.values()
            for operation in operations
        }

    @staticmethod
    def _run(argv: Sequence[str]) -> bytes:
        vector = tuple(argv)
        allowed = {"/usr/bin/dscl", "/usr/bin/dseditgroup", "/bin/launchctl"}
        if (
            not vector
            or vector[0] not in allowed
            or any(not isinstance(item, str) or "\x00" in item for item in vector)
        ):
            raise BrokerExecutorError("MACOS_BACKEND_ARGV_INVALID")
        completed = subprocess.run(
            vector,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            cwd="/",
            env=MacOSInstallBackend._ENV,
            shell=False,
            check=False,
            timeout=60,
        )
        if completed.returncode != 0:
            raise BrokerExecutorError(
                "MACOS_BACKEND_COMMAND_FAILED", f"{vector[0]}:{completed.returncode}"
            )
        return bytes(completed.stdout)

    @staticmethod
    def _launchd_registered(label: str) -> bool:
        if label not in {
            installer.LAUNCHER_PLIST_LABEL,
            installer.ANCHOR_PLIST_LABEL,
            installer.BROKER_PLIST_LABEL,
        }:
            raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_LABEL_INVALID", label)
        completed = subprocess.run(
            ("/bin/launchctl", "print", f"system/{label}"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            cwd="/",
            env=MacOSInstallBackend._ENV,
            shell=False,
            check=False,
            timeout=60,
        )
        if completed.returncode == 0:
            return True
        # Darwin launchctl maps BOOTSTRAP_UNKNOWN_SERVICE to 113.  Refuse all
        # other failures: permission or launchd transport errors are not proof
        # that the fixed label is free.
        error_text = bytes(completed.stderr).decode("utf-8", "replace")
        if completed.returncode == 113 and "Could not find service" in error_text:
            return False
        raise BrokerExecutorError(
            "MACOS_BACKEND_LAUNCHD_ABSENCE_UNPROVEN",
            f"{label}:{completed.returncode}",
        )

    @staticmethod
    def _hash_file(path: Path) -> tuple[os.stat_result, str]:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise BrokerExecutorError("MACOS_BACKEND_FILE_INVALID", str(path))
            digest = hashlib.sha256()
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            return info, "sha256:" + digest.hexdigest()
        finally:
            os.close(fd)

    @staticmethod
    def _verify_root_owned_ancestry(path: Path) -> None:
        parts = _path_parts(path)
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                info = os.fstat(next_fd)
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                    os.close(next_fd)
                    raise BrokerExecutorError("MACOS_BACKEND_ANCESTRY_UNPROTECTED", str(path))
                os.close(fd)
                fd = next_fd
        finally:
            os.close(fd)

    @staticmethod
    def _fsync_parent(path: Path) -> None:
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _account_row(role: str) -> dict[str, object]:
        principal = installer.FIXED_PRINCIPALS[role]
        try:
            by_name = pwd.getpwnam(str(principal["name"]))
            by_uid = pwd.getpwuid(int(principal["uid"]))
            group_name = grp.getgrnam(str(principal["group"]))
            group_gid = grp.getgrgid(int(principal["gid"]))
        except KeyError as error:
            raise BrokerExecutorError("MACOS_BACKEND_IDENTITY_MISSING", role) from error
        if (
            by_name.pw_uid != principal["uid"]
            or by_name.pw_gid != principal["gid"]
            or by_uid.pw_name != principal["name"]
            or group_name.gr_gid != principal["gid"]
            or group_gid.gr_name != principal["group"]
        ):
            raise BrokerExecutorError("MACOS_BACKEND_IDENTITY_MISMATCH", role)
        return {
            "kind": "identity",
            "role": role,
            "name": by_name.pw_name,
            "uid": by_name.pw_uid,
            "gid": by_name.pw_gid,
            "group": group_gid.gr_name,
        }

    @staticmethod
    def _identity_slot_free(role: str) -> None:
        principal = installer.FIXED_PRINCIPALS[role]
        probes = (
            (pwd.getpwnam, str(principal["name"])),
            (pwd.getpwuid, int(principal["uid"])),
            (grp.getgrnam, str(principal["group"])),
            (grp.getgrgid, int(principal["gid"])),
        )
        for probe, value in probes:
            try:
                probe(value)
            except KeyError:
                continue
            raise BrokerExecutorError("MACOS_BACKEND_IDENTITY_SLOT_CONFLICT", role)

    @staticmethod
    def _group_slot_free(role: str) -> None:
        principal = installer.FIXED_PRINCIPALS[role]
        for probe, value in (
            (grp.getgrnam, str(principal["group"])),
            (grp.getgrgid, int(principal["gid"])),
        ):
            try:
                probe(value)
            except KeyError:
                continue
            raise BrokerExecutorError("MACOS_BACKEND_IDENTITY_SLOT_CONFLICT", role)

    @staticmethod
    def _user_slot_free(role: str) -> None:
        principal = installer.FIXED_PRINCIPALS[role]
        for probe, value in (
            (pwd.getpwnam, str(principal["name"])),
            (pwd.getpwuid, int(principal["uid"])),
        ):
            try:
                probe(value)
            except KeyError:
                continue
            raise BrokerExecutorError("MACOS_BACKEND_IDENTITY_SLOT_CONFLICT", role)

    @staticmethod
    def _verify_directory(path: str, uid: int, gid: int, mode: int) -> os.stat_result:
        info = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != uid
            or info.st_gid != gid
            or stat.S_IMODE(info.st_mode) != mode
        ):
            raise BrokerExecutorError("MACOS_BACKEND_DIRECTORY_CONFLICT", path)
        return info

    def _ensure_dir(self, path: str, uid: int, gid: int, mode: int) -> None:
        target = Path(path)
        parent_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        created = False
        try:
            try:
                os.mkdir(target.name, mode, dir_fd=parent_fd)
                created = True
            except FileExistsError:
                pass
            if created:
                fd = os.open(
                    target.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
                )
                try:
                    os.fchown(fd, uid, gid)
                    os.fchmod(fd, mode)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                os.fsync(parent_fd)
            self._verify_directory(path, uid, gid, mode)
        finally:
            os.close(parent_fd)

    def _ensure_parent(self, path: str) -> None:
        if path.startswith(installer.APP_SUPPORT_ROOT + "/"):
            relative = PurePosixPath(path).relative_to(installer.APP_SUPPORT_ROOT)
            current = PurePosixPath(installer.APP_SUPPORT_ROOT)
            spec = self._directories.get(str(current))
            if spec is None:
                raise BrokerExecutorError("MACOS_BACKEND_DIRECTORY_NOT_MANIFESTED", str(current))
            self._ensure_dir(str(current), *spec)
            for part in relative.parts[:-1]:
                current /= part
                spec = self._directories.get(str(current))
                if spec is None:
                    raise BrokerExecutorError(
                        "MACOS_BACKEND_DIRECTORY_NOT_MANIFESTED", str(current)
                    )
                self._ensure_dir(str(current), *spec)
        elif (
            path.startswith(installer.LAUNCH_DAEMONS_DIR + "/")
            or path == installer.PRIVILEGED_HELPER_TOOL
        ):
            # macOS system parents must preexist and are never created here.
            parent = Path(path).parent
            info = os.stat(parent, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise BrokerExecutorError("MACOS_BACKEND_SYSTEM_PARENT_UNPROTECTED", str(parent))
        else:
            raise BrokerExecutorError("MACOS_BACKEND_INSTALL_PATH_OUTSIDE_FIXED_ROOT", path)

    def _verify_target_row(self, row: Mapping[str, object]) -> dict[str, object]:
        path = Path(str(row["path"]))
        self._verify_root_owned_ancestry(path)
        info, digest = self._hash_file(path)
        if (
            info.st_size != row["size"]
            or digest != row["sha256"]
            or info.st_uid != row["uid"]
            or info.st_gid != row["gid"]
            or info.st_mode != row["mode"]
        ):
            raise BrokerExecutorError("MACOS_BACKEND_INSTALL_POSTCONDITION", str(path))
        return {
            "kind": "file",
            "path": str(path),
            "size": info.st_size,
            "mode": info.st_mode,
            "uid": info.st_uid,
            "gid": info.st_gid,
            "dev": info.st_dev,
            "ino": info.st_ino,
            "nlink": info.st_nlink,
            "sha256": digest,
        }

    def _verify_staged_row(self, row: Mapping[str, object]) -> Path:
        source = Path(installer.STAGED_INSTALL_TREE + str(row["path"]))
        self._verify_root_owned_ancestry(source)
        info, digest = self._hash_file(source)
        if (
            info.st_uid != 0
            or info.st_gid != 0
            or info.st_mode & 0o022
            or info.st_size != row["size"]
            or digest != row["sha256"]
        ):
            raise BrokerExecutorError("MACOS_BACKEND_STAGED_PREIMAGE_MISMATCH", str(source))
        return source

    @staticmethod
    def _absent(path: str) -> bool:
        try:
            os.stat(path, follow_symlinks=False)
        except FileNotFoundError:
            return True
        return False

    def _verify_wheel_install_provenance(self) -> None:
        maps_by_distribution: dict[str, list[Mapping[str, object]]] = {}
        for row in self._bundle["python_runtime"]["wheel_install_map"]:
            maps_by_distribution.setdefault(str(row["distribution"]), []).append(row)
        for dependency in self._bundle["python_dependencies"]:
            name = str(dependency["name"])
            wheel_path = Path(str(dependency["wheel_path"]))
            self._verify_root_owned_ancestry(wheel_path)
            fd = os.open(wheel_path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                digest_state = hashlib.sha256()
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    digest_state.update(chunk)
                digest = "sha256:" + digest_state.hexdigest()
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_uid != 0
                    or info.st_gid != 0
                    or info.st_mode & 0o022
                    or info.st_size != dependency["wheel_size"]
                    or digest != dependency["wheel_sha256"]
                ):
                    raise BrokerExecutorError("MACOS_BACKEND_WHEEL_PREIMAGE_MISMATCH", name)
                os.lseek(fd, 0, os.SEEK_SET)
                with (
                    os.fdopen(os.dup(fd), "rb", closefd=True) as wheel_file,
                    zipfile.ZipFile(wheel_file, "r") as archive,
                ):
                    members = [member for member in archive.infolist() if not member.is_dir()]
                    names = [member.filename for member in members]
                    if len(names) != len(set(names)):
                        raise BrokerExecutorError("MACOS_BACKEND_WHEEL_DUPLICATE_MEMBER", name)
                    archive_members = {member.filename: member for member in members}
                    expected_members = {
                        str(row["member_path"]) for row in maps_by_distribution.get(name, [])
                    }
                    if set(archive_members) != expected_members:
                        raise BrokerExecutorError("MACOS_BACKEND_WHEEL_MEMBER_SET_MISMATCH", name)
                    total_size = sum(member.file_size for member in members)
                    if total_size > 256 * 1024 * 1024:
                        raise BrokerExecutorError("MACOS_BACKEND_WHEEL_EXPANSION_OVERSIZE", name)
                    for mapping in maps_by_distribution[name]:
                        member = archive_members[str(mapping["member_path"])]
                        if (
                            member.flag_bits & 1
                            or member.compress_type
                            not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                            or member.file_size > 64 * 1024 * 1024
                            or member.filename.startswith("/")
                            or any(part in {"", ".", ".."} for part in member.filename.split("/"))
                        ):
                            raise BrokerExecutorError(
                                "MACOS_BACKEND_WHEEL_MEMBER_UNSAFE", member.filename
                            )
                        member_mode = (member.external_attr >> 16) & 0o170000
                        if member_mode == stat.S_IFLNK:
                            raise BrokerExecutorError(
                                "MACOS_BACKEND_WHEEL_SYMLINK_FORBIDDEN", member.filename
                            )
                        installed = self._install_rows[str(mapping["install_path"])]
                        if member.file_size != installed["size"]:
                            raise BrokerExecutorError(
                                "MACOS_BACKEND_WHEEL_MEMBER_MISMATCH", member.filename
                            )
                        payload = archive.read(member)
                        if (
                            len(payload) != installed["size"]
                            or "sha256:" + hashlib.sha256(payload).hexdigest()
                            != installed["sha256"]
                        ):
                            raise BrokerExecutorError(
                                "MACOS_BACKEND_WHEEL_MEMBER_MISMATCH", member.filename
                            )
                named = os.stat(wheel_path, follow_symlinks=False)
                if (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
                    raise BrokerExecutorError("MACOS_BACKEND_WHEEL_NAMED_IDENTITY_CHANGED", name)
            finally:
                os.close(fd)

    def _preflight_managed_targets(self) -> None:
        installer.validate_bundle_manifest(self._bundle, require_frozen=True)
        self._verify_staging_exact()
        broker_config_row = self._install_rows[installer.BROKER_CONFIG_PATH]
        broker_config_source = self._verify_staged_row(broker_config_row)
        broker_config = _validate_config(
            _canonical_document(broker_config_source.read_bytes(), "BROKER_CONFIG_STAGED")
        )
        expected_path_map = installer.authority_roster_path_map(
            self._bundle["install_roster"]["entries"]
        )
        if broker_config["installed_roster_path_map"] != expected_path_map:
            raise BrokerExecutorError("MACOS_BACKEND_BROKER_CONFIG_ROSTER_MAP_MISMATCH")
        self._verify_staged_launchd_plists()
        for row in self._install_rows.values():
            self._verify_staged_row(row)
            if not self._absent(str(row["path"])):
                raise BrokerExecutorError("MACOS_BACKEND_TARGET_PREEXISTS", str(row["path"]))
        self._verify_wheel_install_provenance()
        dynamic_absent = (
            installer.SIGNING_KEY_PATH,
            installer.PUBLIC_KEY_REGISTRY_PATH,
            installer.ANCHOR_CONFIG_PATH,
            installer.AUTHORITY_CANDIDATE_PATH,
            installer.AUTHORITY_REGISTRY_PATH,
            installer.PUBLICATION_ACTIVE,
            installer.RUNS_ACTIVE,
            installer.INSTALL_BUNDLE_MANIFEST_PATH,
        )
        for path in dynamic_absent:
            if not self._absent(path):
                raise BrokerExecutorError("MACOS_BACKEND_DYNAMIC_TARGET_PREEXISTS", path)
        self._verify_retained_retry_state()
        self._verify_launchd_slots_free()
        journal_info = os.stat(installer.INSTALL_TRANSITION_JOURNAL_PATH, follow_symlinks=False)
        if (
            not stat.S_ISREG(journal_info.st_mode)
            or journal_info.st_uid != 0
            or journal_info.st_gid != 0
            or stat.S_IMODE(journal_info.st_mode) != 0o600
            or journal_info.st_nlink != 1
        ):
            raise BrokerExecutorError("MACOS_BACKEND_BOOTSTRAP_JOURNAL_INVALID")
        for path, (uid, gid, mode) in self._directories.items():
            try:
                self._verify_directory(path, uid, gid, mode)
            except FileNotFoundError:
                continue
        self._verify_managed_tree_exact(complete=False)

    def _verify_staged_launchd_plists(self) -> None:
        for label, role in (
            (installer.LAUNCHER_PLIST_LABEL, "launcher-plist"),
            (installer.ANCHOR_PLIST_LABEL, "anchor-plist"),
            (installer.BROKER_PLIST_LABEL, "broker-plist"),
        ):
            row = self._install_rows[installer.EXPECTED_ARTIFACT_PATHS[role]]
            source = self._verify_staged_row(row)
            try:
                installer.validate_launchd_plist_bytes(
                    secure_read(
                        source,
                        FilePolicy(0, 0, stat.S_IMODE(int(row["mode"]))),
                        max_bytes=128 * 1024,
                    ),
                    label=label,
                )
            except installer.InstallerError as error:
                raise BrokerExecutorError(
                    "MACOS_BACKEND_STAGED_LAUNCHD_SEMANTICS_INVALID",
                    label,
                ) from error

    def _verify_launchd_slots_free(self) -> None:
        for label in (
            installer.LAUNCHER_PLIST_LABEL,
            installer.ANCHOR_PLIST_LABEL,
            installer.BROKER_PLIST_LABEL,
        ):
            if self._launchd_registered(label):
                raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_LABEL_PREEXISTS", label)

    def _verify_retained_retry_state(self) -> None:
        retained = {
            installer.BROKER_LEDGER_PATH: (installer.BROKER_UID, installer.BROKER_GID, 0o600),
            installer.PUBLIC_RECEIPT_JOURNAL_PATH: (
                installer.BROKER_UID,
                installer.CALLER_GID,
                0o640,
            ),
        }
        for path, (uid, gid, mode) in retained.items():
            if self._absent(path):
                continue
            raw = secure_read(Path(path), FilePolicy(uid, gid, mode), max_bytes=1)
            if raw:
                raise BrokerExecutorError("MACOS_BACKEND_RETRY_DURABLE_STATE_NOT_EMPTY", path)
        if not self._absent(installer.ANCHOR_LOG_PATH):
            expected = anchor_service.encode_genesis_log(self._genesis_anchor())
            actual = secure_read(
                Path(installer.ANCHOR_LOG_PATH),
                FilePolicy(installer.ANCHOR_UID, installer.ANCHOR_GID, 0o600),
                max_bytes=len(expected) + 1,
            )
            if actual != expected:
                raise BrokerExecutorError("MACOS_BACKEND_RETRY_ANCHOR_NOT_GENESIS")

    def _verify_staging_exact(self) -> None:
        expected_files = set(self._source_rows) | {str(STAGED_PLAN_PATH), str(STAGED_MANIFEST_PATH)}
        actual_files, actual_directories = self._walk_paths(installer.STAGED_BUNDLE_ROOT)
        expected_directories = {installer.STAGED_BUNDLE_ROOT}
        for path in expected_files:
            current = str(Path(path).parent)
            while current.startswith(installer.STAGED_BUNDLE_ROOT):
                expected_directories.add(current)
                if current == installer.STAGED_BUNDLE_ROOT:
                    break
                current = str(Path(current).parent)
        if actual_files != expected_files or actual_directories != expected_directories:
            raise BrokerExecutorError("MACOS_BACKEND_STAGING_EXACT_SET_MISMATCH")
        for path in sorted(actual_directories):
            info = os.stat(path, follow_symlinks=False)
            if info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
                raise BrokerExecutorError("MACOS_BACKEND_STAGING_DIRECTORY_UNPROTECTED", path)
        for path, row in self._source_rows.items():
            info, digest = self._hash_file(Path(path))
            if (
                info.st_uid != 0
                or info.st_gid != 0
                or info.st_mode & 0o022
                or info.st_size != row["size"]
                or digest != row["sha256"]
            ):
                raise BrokerExecutorError("MACOS_BACKEND_STAGING_SOURCE_MISMATCH", path)
        for path in (STAGED_PLAN_PATH, STAGED_MANIFEST_PATH):
            info = os.stat(path, follow_symlinks=False)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != 0
                or info.st_gid != 0
                or stat.S_IMODE(info.st_mode) != 0o444
            ):
                raise BrokerExecutorError("MACOS_BACKEND_STAGING_METADATA_UNPROTECTED", str(path))
        staged_plan = _fixed_canonical_json(
            STAGED_PLAN_PATH, FilePolicy(0, 0, 0o444), max_bytes=protocol.MAX_PAYLOAD_BYTES
        )
        _validate_install_plan(staged_plan)
        staged_manifest, staged_raw = _fixed_canonical_json_payload(
            STAGED_MANIFEST_PATH, FilePolicy(0, 0, 0o444), max_bytes=INSTALL_BUNDLE_MAX_BYTES
        )
        if staged_manifest != self._bundle or staged_raw != installer.canonical_bundle_bytes(
            self._bundle
        ):
            raise BrokerExecutorError("MACOS_BACKEND_STAGING_MANIFEST_MISMATCH")

    @staticmethod
    def _walk_paths(root: str) -> tuple[set[str], set[str]]:
        files: set[str] = set()
        directories: set[str] = set()
        if not os.path.lexists(root):
            return files, directories
        root_info = os.stat(root, follow_symlinks=False)
        if not stat.S_ISDIR(root_info.st_mode):
            raise BrokerExecutorError("MACOS_BACKEND_MANAGED_ROOT_INVALID", root)
        directories.add(root)
        pending = [root]
        while pending:
            parent = pending.pop()
            with os.scandir(parent) as entries:
                for entry in entries:
                    path = os.path.join(parent, entry.name)
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        raise BrokerExecutorError("MACOS_BACKEND_MANAGED_SYMLINK_FORBIDDEN", path)
                    if stat.S_ISDIR(info.st_mode):
                        directories.add(path)
                        pending.append(path)
                    elif stat.S_ISREG(info.st_mode):
                        files.add(path)
                    else:
                        raise BrokerExecutorError(
                            "MACOS_BACKEND_MANAGED_SPECIAL_FILE_FORBIDDEN", path
                        )
        return files, directories

    def _verify_managed_tree_exact(
        self,
        *,
        complete: bool,
        dynamic_publications: set[str] | None = None,
    ) -> None:
        actual_files, actual_directories = self._walk_paths(installer.APP_SUPPORT_ROOT)
        allowed_directories = {
            path for path in self._directories if path.startswith(installer.APP_SUPPORT_ROOT)
        } | {
            installer.PUBLICATION_ACTIVE,
            installer.RUNS_ACTIVE,
        }
        dynamic_files = {
            installer.INSTALL_BUNDLE_MANIFEST_PATH,
            installer.BROKER_LEDGER_PATH,
            installer.PUBLIC_RECEIPT_JOURNAL_PATH,
            installer.ANCHOR_LOG_PATH,
            installer.SIGNING_KEY_PATH,
            installer.PUBLIC_KEY_REGISTRY_PATH,
            installer.ANCHOR_CONFIG_PATH,
            installer.AUTHORITY_CANDIDATE_PATH,
            installer.AUTHORITY_REGISTRY_PATH,
        }
        allowed_files = {
            path for path in self._install_rows if path.startswith(installer.APP_SUPPORT_ROOT)
        } | {path for path in dynamic_files if path.startswith(installer.APP_SUPPORT_ROOT)}
        allowed_files.update(dynamic_publications or set())
        if not actual_files <= allowed_files or not actual_directories <= allowed_directories:
            extras = sorted(
                (actual_files - allowed_files) | (actual_directories - allowed_directories)
            )
            raise BrokerExecutorError("MACOS_BACKEND_MANAGED_TREE_EXTRA", ",".join(extras[:8]))
        if complete:
            required_files = allowed_files - {installer.AUTHORITY_CANDIDATE_PATH}
            required_directories = allowed_directories
            if actual_files != required_files or actual_directories != required_directories:
                raise BrokerExecutorError("MACOS_BACKEND_MANAGED_TREE_INCOMPLETE")

    def _install_row(self, row: Mapping[str, object]) -> None:
        source = self._verify_staged_row(row)
        path = Path(str(row["path"]))
        self._ensure_parent(str(path))
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        temp_name = self._publication_temp_name(path)
        target_fd = -1
        linked = False
        try:
            try:
                os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise BrokerExecutorError("MACOS_BACKEND_TARGET_PREEXISTS", str(path))
            target_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            os.fchown(target_fd, int(row["uid"]), int(row["gid"]))
            os.fchmod(target_fd, stat.S_IMODE(int(row["mode"])))
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                offset = 0
                while offset < len(chunk):
                    written = os.write(target_fd, chunk[offset:])
                    if written <= 0:
                        raise BrokerExecutorError("MACOS_BACKEND_ZERO_WRITE", str(path))
                    offset += written
            os.fsync(target_fd)
            os.link(
                temp_name,
                path.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            linked = True
            os.unlink(temp_name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            os.close(source_fd)
            if target_fd >= 0:
                os.close(target_fd)
            if not linked:
                with suppress(FileNotFoundError):
                    os.unlink(temp_name, dir_fd=parent_fd)
            os.close(parent_fd)
        self._verify_target_row(row)

    def _rows_for_step(self, step_id: str) -> list[dict[str, object]]:
        rows = list(self._install_rows.values())
        code_prefixes = (
            installer.PYTHON_SITE_PACKAGES + "/runtime/",
            installer.PYTHON_SITE_PACKAGES + "/metis_model1/",
            installer.APP_SUPPORT_ROOT + "/broker/",
            installer.APP_SUPPORT_ROOT + "/anchor/",
        )
        if step_id == "install-broker-code":
            fixed = {installer.PUBLIC_FIXTURE_REGISTRY_PATH, installer.BROKER_CONFIG_PATH}
            return [
                row
                for row in rows
                if str(row["path"]).startswith(code_prefixes) or str(row["path"]) in fixed
            ]
        if step_id == "install-runtime":
            code_paths = {str(row["path"]) for row in self._rows_for_step("install-broker-code")}
            return [
                row
                for row in rows
                if (
                    str(row["path"]).startswith(installer.PYTHON_ROOT + "/")
                    or str(row["path"]) == installer.EXPECTED_ARTIFACT_PATHS["node"]
                )
                and str(row["path"]) not in code_paths
            ]
        if step_id == "install-release":
            node_path = installer.EXPECTED_ARTIFACT_PATHS["node"]
            return [
                row
                for row in rows
                if str(row["path"]).startswith(installer.RELEASE_ROOT + "/")
                and str(row["path"]) != node_path
            ]
        if step_id == "install-launcher":
            return [self._install_rows[installer.PRIVILEGED_HELPER_TOOL]]
        if step_id == "install-launchd-plists":
            return [
                self._install_rows[installer.EXPECTED_ARTIFACT_PATHS[role]]
                for role in ("launcher-plist", "anchor-plist", "broker-plist")
            ]
        return []

    def _install_step_rows(self, step_id: str) -> None:
        rows = self._rows_for_step(step_id)
        if not rows:
            raise BrokerExecutorError("MACOS_BACKEND_INSTALL_GROUP_EMPTY", step_id)
        for row in sorted(rows, key=lambda item: str(item["path"])):
            self._install_row(row)

    def _verify_step_rows(self, step_id: str) -> list[dict[str, object]]:
        rows = self._rows_for_step(step_id)
        if not rows:
            raise BrokerExecutorError("MACOS_BACKEND_VERIFY_GROUP_EMPTY", step_id)
        return [
            self._verify_target_row(row) for row in sorted(rows, key=lambda item: str(item["path"]))
        ]

    def _write_exclusive(
        self, path: Path, payload: bytes, *, uid: int, gid: int, mode: int
    ) -> None:
        self._ensure_parent(str(path))
        parent_info = os.stat(path.parent, follow_symlinks=False)
        if parent_info.st_uid != 0 or parent_info.st_mode & 0o022:
            raise BrokerExecutorError("MACOS_BACKEND_PUBLICATION_PARENT_UNPROTECTED", str(path))
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        temp_name = self._publication_temp_name(path)
        fd = -1
        linked = False
        try:
            fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                mode,
                dir_fd=parent_fd,
            )
            os.fchown(fd, uid, gid)
            os.fchmod(fd, mode)
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise BrokerExecutorError("MACOS_BACKEND_ZERO_WRITE", str(path))
                offset += written
            os.fsync(fd)
            os.link(
                temp_name,
                path.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            linked = True
            os.unlink(temp_name, dir_fd=parent_fd)
            named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                named.st_uid != uid
                or named.st_gid != gid
                or stat.S_IMODE(named.st_mode) != mode
                or named.st_nlink != 1
            ):
                raise BrokerExecutorError("MACOS_BACKEND_PUBLICATION_POSTCONDITION", str(path))
            os.fsync(parent_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            if not linked:
                with suppress(FileNotFoundError):
                    os.unlink(temp_name, dir_fd=parent_fd)
            os.close(parent_fd)

    @staticmethod
    def _canonical_digest(rows: Sequence[Mapping[str, object]]) -> str:
        payload = protocol.canonical_bytes(list(rows))
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _publication_temp_name(path: Path) -> str:
        return f".{path.name}.w3-tmp-{hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:24]}"

    @classmethod
    def _publication_temp_path(cls, path: str) -> str:
        target = Path(path)
        return str(target.with_name(cls._publication_temp_name(target)))

    def _precreate_leaf(
        self, path: str, *, uid: int, gid: int, mode: int, directory: bool = False
    ) -> None:
        self._ensure_parent(path)
        if directory:
            self._ensure_dir(path, uid, gid, mode)
            return
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        try:
            os.fchown(fd, uid, gid)
            os.fchmod(fd, mode)
            os.fsync(fd)
        finally:
            os.close(fd)
        self._fsync_parent(Path(path))

    def _create_signing_seed(self) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = Ed25519PrivateKey.generate()
        seed = key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        if len(seed) != 32:
            raise BrokerExecutorError("MACOS_BACKEND_KEY_GENERATION_INVALID")
        self._write_exclusive(
            Path(installer.SIGNING_KEY_PATH), seed, uid=0, gid=installer.BROKER_GID, mode=0o440
        )

    def _publish_public_key_registry(self) -> None:
        seed = secure_read(
            Path(installer.SIGNING_KEY_PATH), FilePolicy(0, installer.BROKER_GID, 0o440)
        )
        public_key = protocol.ed25519.derive_public_key(seed)
        registry = {
            "schema_version": 1,
            "kind": PUBLIC_KEY_REGISTRY_KIND,
            "keys": [
                {
                    "mode": protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
                    "algorithm": protocol.PRODUCTION_ALGORITHM,
                    "key_id": protocol.ed25519.mode_scoped_key_id(
                        public_key, mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC
                    ),
                    "public_key": protocol.ed25519.encode_public_key(public_key),
                }
            ],
        }
        self._write_exclusive(
            Path(installer.PUBLIC_KEY_REGISTRY_PATH),
            protocol.canonical_bytes(registry),
            uid=0,
            gid=0,
            mode=0o444,
        )

    def _measure_receipt_path(self, path: str) -> dict[str, object]:
        info = os.stat(path, follow_symlinks=False)
        row: dict[str, object] = {
            "kind": "directory" if stat.S_ISDIR(info.st_mode) else "file",
            "path": path,
            "mode": info.st_mode,
            "uid": info.st_uid,
            "gid": info.st_gid,
            "dev": info.st_dev,
            "ino": info.st_ino,
            "nlink": info.st_nlink,
        }
        if stat.S_ISREG(info.st_mode) and path not in self._MUTABLE_RECEIPT_PATHS:
            _, digest = self._hash_file(Path(path))
            row.update({"size": info.st_size, "sha256": digest})
        return row

    def _receipt_targets(self, step_id: str) -> list[dict[str, object]]:
        role_for_identity = {
            "create-identity-metisbroker": "broker",
            "create-identity-metisrunner": "runner",
            "create-identity-metisanchor": "anchor",
        }
        if step_id in role_for_identity:
            return [self._account_row(role_for_identity[step_id])]
        if step_id in {
            "install-broker-code",
            "install-runtime",
            "install-release",
            "install-launcher",
            "install-launchd-plists",
        }:
            rows = self._verify_step_rows(step_id)
            if step_id == "install-broker-code":
                rows.append(self._measure_receipt_path(installer.INSTALL_BUNDLE_MANIFEST_PATH))
            return rows
        if step_id == "precreate-durable-leaves":
            paths = (
                installer.BROKER_LEDGER_PATH,
                installer.INSTALL_TRANSITION_JOURNAL_PATH,
                installer.PUBLIC_RECEIPT_JOURNAL_PATH,
                installer.ANCHOR_LOG_PATH,
                installer.PUBLICATION_ACTIVE,
                installer.RUNS_PARENT,
                installer.RUNS_ACTIVE,
            )
            return [self._measure_receipt_path(path) for path in paths]
        if step_id == "provision-signing-key":
            return [
                self._measure_receipt_path(installer.SIGNING_KEY_PATH),
                self._measure_receipt_path(installer.PUBLIC_KEY_REGISTRY_PATH),
                self._measure_receipt_path(installer.AUTHORITY_CANDIDATE_PATH),
                self._measure_receipt_path(installer.ANCHOR_CONFIG_PATH),
            ]
        labels = {
            "bootstrap-launcher": (
                installer.LAUNCHER_PLIST_LABEL,
                installer.EXPECTED_ARTIFACT_PATHS["launcher-plist"],
            ),
            "bootstrap-anchor": (
                installer.ANCHOR_PLIST_LABEL,
                installer.EXPECTED_ARTIFACT_PATHS["anchor-plist"],
            ),
            "bootstrap-broker": (
                installer.BROKER_PLIST_LABEL,
                installer.EXPECTED_ARTIFACT_PATHS["broker-plist"],
            ),
        }
        if step_id in labels:
            label, plist = labels[step_id]
            return [self._launchd_job_receipt(label, plist)]
        if step_id == "register-authority":
            return [self._measure_receipt_path(installer.AUTHORITY_REGISTRY_PATH)]
        return []

    def _ownership_receipt(self, step_id: str) -> dict[str, object] | None:
        targets = self._receipt_targets(step_id)
        if not targets:
            return None
        return {
            "schema_version": 1,
            "kind": "w3-phase-b-install-ownership-receipt",
            "step_id": step_id,
            "targets": len(targets),
            "targets_sha256": self._canonical_digest(targets),
            "target_roster": targets,
        }

    def _validate_ownership_receipt(
        self,
        step_id: str,
        receipt: Mapping[str, object],
    ) -> tuple[dict[str, object], ...]:
        kind = receipt.get("kind")
        if kind in {
            "w3-phase-b-install-ownership-receipt",
            "w3-phase-b-install-operation-receipt",
        }:
            fields = {
                "schema_version",
                "kind",
                "step_id",
                "targets",
                "targets_sha256",
                "target_roster",
            }
            if kind == "w3-phase-b-install-operation-receipt":
                fields.add("operation_id")
            roster = receipt.get("target_roster")
            if (
                set(receipt) != fields
                or receipt.get("schema_version") != 1
                or receipt.get("step_id") != step_id
                or not isinstance(roster, list)
                or not roster
                or receipt.get("targets") != len(roster)
                or receipt.get("targets_sha256") != self._canonical_digest(roster)
                or any(not isinstance(row, dict) for row in roster)
            ):
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_RECEIPT_INVALID", step_id)
            return tuple(dict(row) for row in roster)
        if kind == "w3-phase-b-install-partial-ownership-receipt":
            fields = {"schema_version", "kind", "step_id", "operations", "operations_sha256"}
            operations = receipt.get("operations")
            if (
                set(receipt) != fields
                or receipt.get("schema_version") != 1
                or receipt.get("step_id") != step_id
                or not isinstance(operations, list)
                or not operations
                or receipt.get("operations_sha256")
                != "sha256:" + hashlib.sha256(protocol.canonical_bytes(operations)).hexdigest()
            ):
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_RECEIPT_INVALID", step_id)
            rows: list[dict[str, object]] = []
            seen: set[str] = set()
            for operation in operations:
                if not isinstance(operation, dict) or set(operation) != {
                    "operation_id",
                    "ownership_receipt",
                }:
                    raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_RECEIPT_INVALID", step_id)
                operation_id = operation["operation_id"]
                nested = operation["ownership_receipt"]
                if (
                    not isinstance(operation_id, str)
                    or operation_id in seen
                    or not isinstance(nested, Mapping)
                    or nested.get("operation_id") != operation_id
                ):
                    raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_RECEIPT_INVALID", step_id)
                seen.add(operation_id)
                rows.extend(self._validate_ownership_receipt(step_id, nested))
            return tuple(rows)
        raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_RECEIPT_INVALID", step_id)

    @staticmethod
    def _partial_operation_ids(receipt: Mapping[str, object]) -> tuple[str, ...]:
        if receipt.get("kind") != "w3-phase-b-install-partial-ownership-receipt":
            return ()
        operations = receipt.get("operations")
        if not isinstance(operations, list):
            return ()
        return tuple(
            str(row["operation_id"])
            for row in operations
            if isinstance(row, Mapping) and isinstance(row.get("operation_id"), str)
        )

    def _operation_targets(self, step_id: str, operation: str) -> list[dict[str, object]]:
        base = operation.split("::", 1)[0]
        if "::file:" in operation:
            return [self._verify_target_row(self._row_for_unit(base, operation))]
        if "::directory:" in operation:
            suffix = operation.rsplit(":", 1)[-1]
            paths = [path for path in self._directories if self._unit_suffix(path) == suffix]
            if len(paths) != 1:
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_UNIT_COLLISION", operation)
            return [self._measure_receipt_path(paths[0])]
        if operation == "install-root-owned-python-service-closure::bundle-manifest":
            return [self._measure_receipt_path(installer.INSTALL_BUNDLE_MANIFEST_PATH)]
        operation = base
        if operation.startswith(("create-group-record-", "set-group-primary-gid-")):
            gid = operation.rsplit("-", 1)[-1]
            role = {"499": "broker", "498": "runner", "497": "anchor"}[gid]
            principal = installer.FIXED_PRINCIPALS[role]
            raw = self._run(("/usr/bin/dscl", ".", "-read", f"/Groups/{principal['group']}"))
            return [
                {
                    "kind": "directory-service-record",
                    "record": f"/Groups/{principal['group']}",
                    "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                }
            ]
        if operation.startswith(
            (
                "create-user-record-",
                "set-user-unique-id-",
                "set-user-primary-gid-",
                "set-user-home-",
                "set-user-shell-",
            )
        ):
            uid = operation.rsplit("-", 1)[-1]
            role = {"499": "broker", "498": "runner", "497": "anchor"}[uid]
            principal = installer.FIXED_PRINCIPALS[role]
            raw = self._run(("/usr/bin/dscl", ".", "-read", f"/Users/{principal['name']}"))
            return [
                {
                    "kind": "directory-service-record",
                    "record": f"/Users/{principal['name']}",
                    "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                }
            ]
        if operation == "install-fixed-directory-roster":
            return [self._measure_receipt_path(path) for path in sorted(self._directories)]
        if operation in {
            "install-root-owned-python-service-closure",
            "install-cpython-3.13.3-symlink-free",
            "install-public-capsule",
            "install-privileged-launcher",
        }:
            return self._verify_step_rows(step_id)
        if operation == "install-stable-release-slot":
            return [self._measure_receipt_path(installer.RELEASE_ROOT)]
        if operation.startswith("precreate-") or operation == "verify-bootstrap-install-journal":
            paths = {
                "precreate-ledger": installer.BROKER_LEDGER_PATH,
                "verify-bootstrap-install-journal": installer.INSTALL_TRANSITION_JOURNAL_PATH,
                "precreate-public-receipt-journal": installer.PUBLIC_RECEIPT_JOURNAL_PATH,
                "precreate-anchor-genesis": installer.ANCHOR_LOG_PATH,
                "precreate-publication-active": installer.PUBLICATION_ACTIVE,
                "precreate-runs-active": installer.RUNS_ACTIVE,
            }
            if operation in paths:
                return [self._measure_receipt_path(paths[operation])]
        if operation == "create-exclusive-ed25519-seed-cryptography47":
            return [self._measure_receipt_path(installer.SIGNING_KEY_PATH)]
        if operation == "publish-public-key-registry-no-clobber":
            return [self._measure_receipt_path(installer.PUBLIC_KEY_REGISTRY_PATH)]
        if operation == "prepare-authority-candidate-no-clobber":
            return [self._measure_receipt_path(installer.AUTHORITY_CANDIDATE_PATH)]
        if operation == "prepare-anchor-config-no-clobber":
            return [self._measure_receipt_path(installer.ANCHOR_CONFIG_PATH)]
        if operation.startswith("install-") and operation.endswith("-plist"):
            role = {
                "install-launcher-plist": "launcher-plist",
                "install-anchor-plist": "anchor-plist",
                "install-broker-plist": "broker-plist",
            }[operation]
            return [self._measure_receipt_path(installer.EXPECTED_ARTIFACT_PATHS[role])]
        if operation in self._LAUNCHD_BOOTSTRAP_OPERATIONS:
            label, plist = self._LAUNCHD_BOOTSTRAP_OPERATIONS[operation]
            return [self._launchd_job_receipt(label, plist)]
        if operation in self._LAUNCHD_KICKSTART_OPERATIONS:
            label, plist = self._LAUNCHD_KICKSTART_OPERATIONS[operation]
            return [self._launchd_job_receipt(label, plist, require_live=True)]
        if operation == "activate-prepared-authority-cas-last":
            return [self._measure_receipt_path(installer.AUTHORITY_REGISTRY_PATH)]
        return []

    def _operation_receipt(self, step_id: str, operation: str) -> dict[str, object] | None:
        targets = self._operation_targets(step_id, operation)
        if not targets:
            return None
        return {
            "schema_version": 1,
            "kind": "w3-phase-b-install-operation-receipt",
            "step_id": step_id,
            "operation_id": operation,
            "targets": len(targets),
            "targets_sha256": self._canonical_digest(targets),
            "target_roster": targets,
        }

    def _launchd_plist_identity(self, label: str, plist_path: str) -> dict[str, object]:
        row = self._install_rows.get(plist_path)
        if not isinstance(row, Mapping):
            raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_PLIST_UNMANIFESTED", label)
        try:
            document = installer.validate_launchd_plist_bytes(
                secure_read(
                    Path(plist_path),
                    FilePolicy(int(row["uid"]), int(row["gid"]), stat.S_IMODE(int(row["mode"]))),
                    max_bytes=128 * 1024,
                ),
                label=label,
            )
        except installer.InstallerError as error:
            raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_PLIST_INVALID", label) from error
        arguments = document["ProgramArguments"]
        return {
            "kind": "launchd-registration",
            "label": label,
            "program_arguments": list(arguments),
            "package_instance": installer.LAUNCHD_PACKAGE_INSTANCE,
            "plist_semantics_sha256": "sha256:"
            + hashlib.sha256(protocol.canonical_bytes(document)).hexdigest(),
            "plist": self._measure_receipt_path(plist_path),
        }

    @staticmethod
    def _parse_launchd_print_identity(payload: bytes, label: str) -> dict[str, object]:
        try:
            text = payload.decode("utf-8", "strict")
        except UnicodeDecodeError as error:
            raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_PRINT_INVALID", label) from error
        if (
            not text
            or "\x00" in text
            or any(ord(character) < 0x20 and character not in "\n\r\t" for character in text)
        ):
            raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_PRINT_INVALID", label)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines or lines[0] != f"system/{label} = {{" or lines[-1] != "}":
            raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_PRINT_INVALID", label)

        def scalar(name: str) -> str:
            pattern = re.compile(rf"^{re.escape(name)} = (.+)$")
            values = [
                match.group(1) for line in lines for match in [pattern.fullmatch(line)] if match
            ]
            if len(values) != 1:
                raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_PRINT_INVALID", f"{label}:{name}")
            return values[0]

        def block(name: str) -> list[str]:
            starts = [index for index, line in enumerate(lines) if line == f"{name} = {{"]
            if len(starts) != 1:
                raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_PRINT_INVALID", f"{label}:{name}")
            depth = 1
            values: list[str] = []
            for line in lines[starts[0] + 1 :]:
                if line.endswith("= {"):
                    depth += 1
                elif line == "}":
                    depth -= 1
                    if depth == 0:
                        return values
                elif depth == 1:
                    values.append(line)
            raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_PRINT_INVALID", f"{label}:{name}")

        arguments = block("arguments")
        environment_rows = block("environment")
        environment: dict[str, str] = {}
        for row in environment_rows:
            pair = row.split(" => ", 1)
            if len(pair) != 2 or not pair[0] or pair[0] in environment:
                raise BrokerExecutorError(
                    "MACOS_BACKEND_LAUNCHD_PRINT_INVALID", f"{label}:environment"
                )
            environment[pair[0]] = pair[1]

        def optional_scalar(name: str) -> str | None:
            pattern = re.compile(rf"^{re.escape(name)} = (.+)$")
            values = [
                match.group(1) for line in lines for match in [pattern.fullmatch(line)] if match
            ]
            if len(values) > 1:
                raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_PRINT_INVALID", f"{label}:{name}")
            return values[0] if values else None

        pid_text = optional_scalar("pid")
        if pid_text is not None and re.fullmatch(r"[1-9][0-9]*", pid_text) is None:
            raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_PRINT_INVALID", f"{label}:pid")
        return {
            "label": label,
            "path": scalar("path"),
            "program": scalar("program"),
            "program_arguments": arguments,
            "package_instance": environment.get(installer.LAUNCHD_PACKAGE_INSTANCE_KEY),
            "state": optional_scalar("state"),
            "pid": None if pid_text is None else int(pid_text),
        }

    def _launchd_job_receipt(
        self,
        label: str,
        plist_path: str,
        *,
        require_live: bool = False,
    ) -> dict[str, object]:
        identity = self._launchd_plist_identity(label, plist_path)
        output = self._run(("/bin/launchctl", "print", f"system/{label}"))
        observed = self._parse_launchd_print_identity(output, label)
        structural = {
            "label": label,
            "path": plist_path,
            "program": identity["program_arguments"][0],
            "program_arguments": identity["program_arguments"],
            "package_instance": identity["package_instance"],
        }
        if {key: observed[key] for key in structural} != structural:
            raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_JOB_IDENTITY_MISMATCH", label)
        if require_live and (
            observed["state"] != "running"
            or type(observed["pid"]) is not int
            or int(observed["pid"]) <= 0
        ):
            raise BrokerExecutorError("MACOS_BACKEND_SERVICE_NOT_LIVE", label)
        return identity

    @staticmethod
    def _active_authority_sha256() -> str:
        try:
            authority = protocol.validate_authority(
                _canonical_document(
                    secure_read(
                        Path(installer.AUTHORITY_REGISTRY_PATH),
                        FilePolicy(0, 0, 0o444),
                    ),
                    "AUTHORITY",
                )
            )
        except (BrokerExecutorError, protocol.BrokerProtocolError) as error:
            raise BrokerExecutorError("MACOS_BACKEND_ACTIVE_AUTHORITY_INVALID") from error
        return protocol.authority_hash(authority)

    def _poll_launchd_live(self, label: str, plist_path: str) -> dict[str, object]:
        last_error: BrokerExecutorError | None = None
        for attempt in range(self._LAUNCHD_POLL_ATTEMPTS):
            try:
                return self._launchd_job_receipt(label, plist_path, require_live=True)
            except BrokerExecutorError as error:
                if error.code != "MACOS_BACKEND_SERVICE_NOT_LIVE":
                    raise
                last_error = error
            if attempt + 1 < self._LAUNCHD_POLL_ATTEMPTS:
                time.sleep(self._LAUNCHD_POLL_INTERVAL_SECONDS)
        raise BrokerExecutorError("MACOS_BACKEND_SERVICE_START_TIMEOUT", label) from last_error

    def operation_intent(self, step_id: str, operation: str) -> Mapping[str, object] | None:
        if step_id == "register-authority" and operation == "activate-prepared-authority-cas-last":
            authority = self._prepared_authority()
            candidate = self._measure_receipt_path(installer.AUTHORITY_CANDIDATE_PATH)
            if not self._absent(installer.AUTHORITY_REGISTRY_PATH):
                raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_ALREADY_ACTIVE")
            intent = {
                "kind": "authority-cas-intent",
                "candidate": candidate,
                "authority_sha256": protocol.authority_hash(authority),
                "active_path": installer.AUTHORITY_REGISTRY_PATH,
                "active_precondition": "absent",
            }
            self._pending_operation_intents[(step_id, operation)] = intent
            return intent
        base = operation.split("::", 1)[0]
        targets: list[dict[str, object]] = []
        if "::file:" in operation:
            row = dict(self._row_for_unit(base, operation))
            targets.append(
                {
                    "kind": "file",
                    "path": row["path"],
                    "temp_path": self._publication_temp_path(str(row["path"])),
                    "precondition": "absent",
                    "expected": row,
                }
            )
        elif "::directory:" in operation:
            suffix = operation.rsplit(":", 1)[-1]
            paths = [path for path in self._directories if self._unit_suffix(path) == suffix]
            if len(paths) != 1:
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_UNIT_COLLISION", operation)
            path = paths[0]
            uid, gid, mode = self._directories[path]
            targets.append(
                {
                    "kind": "directory",
                    "path": path,
                    "precondition": "exact-existing" if not self._absent(path) else "absent",
                    "uid": uid,
                    "gid": gid,
                    "mode": mode,
                }
            )
        elif operation == "install-root-owned-python-service-closure::bundle-manifest":
            targets.append(
                {
                    "kind": "file",
                    "path": installer.INSTALL_BUNDLE_MANIFEST_PATH,
                    "temp_path": self._publication_temp_path(
                        installer.INSTALL_BUNDLE_MANIFEST_PATH
                    ),
                    "precondition": "absent",
                    "sha256": self._bundle["bundle_sha256"],
                }
            )
        else:
            fixed_paths = {
                "precreate-ledger": installer.BROKER_LEDGER_PATH,
                "precreate-public-receipt-journal": installer.PUBLIC_RECEIPT_JOURNAL_PATH,
                "precreate-anchor-genesis": installer.ANCHOR_LOG_PATH,
                "precreate-publication-active": installer.PUBLICATION_ACTIVE,
                "precreate-runs-active": installer.RUNS_ACTIVE,
                "create-exclusive-ed25519-seed-cryptography47": installer.SIGNING_KEY_PATH,
                "publish-public-key-registry-no-clobber": installer.PUBLIC_KEY_REGISTRY_PATH,
                "prepare-authority-candidate-no-clobber": installer.AUTHORITY_CANDIDATE_PATH,
                "prepare-anchor-config-no-clobber": installer.ANCHOR_CONFIG_PATH,
                "install-launcher-plist": installer.EXPECTED_ARTIFACT_PATHS["launcher-plist"],
                "install-anchor-plist": installer.EXPECTED_ARTIFACT_PATHS["anchor-plist"],
                "install-broker-plist": installer.EXPECTED_ARTIFACT_PATHS["broker-plist"],
            }
            if operation in fixed_paths:
                precondition = "absent"
                if operation in {
                    "precreate-ledger",
                    "precreate-public-receipt-journal",
                    "precreate-anchor-genesis",
                } and not self._absent(fixed_paths[operation]):
                    precondition = "exact-existing"
                directory_specs = {
                    "precreate-publication-active": (
                        installer.BROKER_UID,
                        installer.BROKER_GID,
                        0o700,
                    ),
                    "precreate-runs-active": (installer.RUNNER_UID, installer.RUNNER_GID, 0o700),
                }
                target: dict[str, object] = {
                    "kind": "directory" if operation in directory_specs else "path",
                    "path": fixed_paths[operation],
                    "precondition": precondition,
                }
                if operation in directory_specs:
                    target.update(
                        zip(("uid", "gid", "mode"), directory_specs[operation], strict=True)
                    )
                if operation in {
                    "precreate-anchor-genesis",
                    "create-exclusive-ed25519-seed-cryptography47",
                    "publish-public-key-registry-no-clobber",
                    "prepare-authority-candidate-no-clobber",
                    "prepare-anchor-config-no-clobber",
                    "install-launcher-plist",
                    "install-anchor-plist",
                    "install-broker-plist",
                }:
                    target["temp_path"] = self._publication_temp_path(str(fixed_paths[operation]))
                if operation == "prepare-authority-candidate-no-clobber":
                    target["expected_sha256"] = protocol.authority_hash(self._build_authority())
                elif operation == "prepare-anchor-config-no-clobber":
                    target["active_authority_sha256"] = protocol.authority_hash(
                        self._prepared_authority()
                    )
                targets.append(target)
            elif operation.startswith(("create-group-record-", "create-user-record-")):
                targets.append(
                    {
                        "kind": "directory-service-record",
                        "operation": operation,
                        "precondition": "absent-fixed-slot",
                    }
                )
            elif operation.startswith(("set-group-primary-gid-", "set-user-")):
                targets.append(
                    {
                        "kind": "directory-service-record",
                        "operation": operation,
                        "precondition": "transaction-created-record",
                    }
                )
            elif operation in self._LAUNCHD_BOOTSTRAP_OPERATIONS:
                label, plist = self._LAUNCHD_BOOTSTRAP_OPERATIONS[operation]
                target = self._launchd_plist_identity(label, plist)
                target["precondition"] = "label-absent"
                target["action"] = "bootstrap"
                targets.append(target)
            elif operation in self._LAUNCHD_KICKSTART_OPERATIONS:
                label, plist = self._LAUNCHD_KICKSTART_OPERATIONS[operation]
                observed = self._launchd_job_receipt(label, plist)
                target = dict(observed)
                target["precondition"] = "registered-exact"
                target["action"] = "kickstart"
                target["active_authority_sha256"] = self._active_authority_sha256()
                targets.append(target)
        if not targets:
            self._pending_operation_intents[(step_id, operation)] = None
            return None
        intent = {
            "kind": "fixed-operation-intent",
            "step_id": step_id,
            "operation_id": operation,
            "targets": targets,
        }
        self._pending_operation_intents[(step_id, operation)] = intent
        return intent

    @staticmethod
    def _unit_suffix(path: str) -> str:
        return hashlib.sha256(path.encode("utf-8")).hexdigest()

    def operation_units(self, step_id: str, operation: str) -> tuple[str, ...]:
        if operation == "install-fixed-directory-roster":
            paths = sorted(self._directories, key=lambda path: (path.count("/"), path))
            return tuple(f"{operation}::directory:{self._unit_suffix(path)}" for path in paths)
        row_steps = {
            "install-root-owned-python-service-closure": "install-broker-code",
            "install-cpython-3.13.3-symlink-free": "install-runtime",
            "install-public-capsule": "install-release",
            "install-privileged-launcher": "install-launcher",
        }
        if operation in row_steps:
            rows = sorted(
                self._rows_for_step(row_steps[operation]), key=lambda row: str(row["path"])
            )
            units = [f"{operation}::file:{self._unit_suffix(str(row['path']))}" for row in rows]
            if operation == "install-root-owned-python-service-closure":
                units.append(f"{operation}::bundle-manifest")
            return tuple(units)
        return (operation,)

    def _row_for_unit(self, base: str, unit: str) -> Mapping[str, object]:
        prefix = base + "::file:"
        if not unit.startswith(prefix):
            raise BrokerExecutorError("MACOS_BACKEND_OPERATION_UNIT_INVALID", unit)
        suffix = unit[len(prefix) :]
        matches = [
            row
            for row in self._install_rows.values()
            if self._unit_suffix(str(row["path"])) == suffix
        ]
        if len(matches) != 1:
            raise BrokerExecutorError("MACOS_BACKEND_OPERATION_UNIT_COLLISION", unit)
        return matches[0]

    def _apply_operation_unit(self, step_id: str, operation: str) -> None:
        base = operation.split("::", 1)[0]
        if operation == base:
            self._perform(base, step_id)
            return
        if base == "install-fixed-directory-roster" and "::directory:" in operation:
            suffix = operation.rsplit(":", 1)[-1]
            matches = [
                (path, spec)
                for path, spec in self._directories.items()
                if self._unit_suffix(path) == suffix
            ]
            if len(matches) != 1:
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_UNIT_COLLISION", operation)
            path, spec = matches[0]
            self._ensure_dir(path, *spec)
            return
        if operation == "install-root-owned-python-service-closure::bundle-manifest":
            self._write_exclusive(
                Path(installer.INSTALL_BUNDLE_MANIFEST_PATH),
                installer.canonical_bundle_bytes(self._bundle),
                uid=0,
                gid=0,
                mode=0o444,
            )
            return
        if base in {
            "install-root-owned-python-service-closure",
            "install-cpython-3.13.3-symlink-free",
            "install-public-capsule",
            "install-privileged-launcher",
        }:
            self._install_row(self._row_for_unit(base, operation))
            return
        raise BrokerExecutorError("MACOS_BACKEND_OPERATION_UNIT_INVALID", operation)

    def apply_operation(self, step_id: str, operation: str) -> BackendEffect:
        base = operation.split("::", 1)[0]
        if base not in installer.MACOS_BACKEND_OPERATION_ROSTER.get(step_id, ()):
            raise BrokerExecutorError("MACOS_BACKEND_OPERATION_NOT_IN_STEP", operation)
        self._apply_operation_unit(step_id, operation)
        intent = self._pending_operation_intents.pop((step_id, operation), None)
        receipt = self._operation_receipt(step_id, operation)
        if isinstance(intent, Mapping) and intent.get("kind") == "fixed-operation-intent":
            targets = intent.get("targets")
            if (
                isinstance(targets, list)
                and targets
                and all(
                    isinstance(target, Mapping) and target.get("precondition") == "exact-existing"
                    for target in targets
                )
            ):
                receipt = None
        if operation in {"verify-bootstrap-install-journal", "install-stable-release-slot"}:
            receipt = None
        return BackendEffect(1, receipt)

    def step_ownership_receipt(self, step_id: str) -> Mapping[str, object] | None:
        return self._ownership_receipt(step_id)

    def activation_receipt_from_intent(
        self, intent: Mapping[str, object]
    ) -> OperationReconciliation:
        if (
            intent.get("kind") != "authority-cas-intent"
            or intent.get("active_path") != installer.AUTHORITY_REGISTRY_PATH
        ):
            raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_CAS_INTENT_INVALID")
        candidate_receipt = intent.get("candidate")
        if not isinstance(candidate_receipt, Mapping):
            raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_CAS_INTENT_INVALID")
        parent = Path(installer.AUTHORITY_REGISTRY_PATH).parent
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:

            def named(name: str) -> os.stat_result | None:
                try:
                    return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    return None

            candidate = named(Path(installer.AUTHORITY_CANDIDATE_PATH).name)
            active_info = named(Path(installer.AUTHORITY_REGISTRY_PATH).name)
            if active_info is None:
                if candidate is None:
                    raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_CAS_SUBSTATE_INVALID")
                if (
                    candidate.st_dev != candidate_receipt.get("dev")
                    or candidate.st_ino != candidate_receipt.get("ino")
                    or candidate.st_nlink != 1
                ):
                    raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_CAS_SUBSTATE_INVALID")
                return OperationReconciliation("not-applied")
            if (
                candidate is not None
                and (candidate.st_dev, candidate.st_ino) == (active_info.st_dev, active_info.st_ino)
                and candidate.st_nlink == active_info.st_nlink == 2
                and candidate.st_dev == candidate_receipt.get("dev")
                and candidate.st_ino == candidate_receipt.get("ino")
            ):
                fd = os.open(
                    Path(installer.AUTHORITY_REGISTRY_PATH).name,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
                try:
                    info = os.fstat(fd)
                    payload = bytearray()
                    while True:
                        chunk = os.read(fd, 1024 * 1024)
                        if not chunk:
                            break
                        payload.extend(chunk)
                    if (
                        info.st_uid != 0
                        or info.st_gid != 0
                        or stat.S_IMODE(info.st_mode) != 0o444
                        or protocol.authority_hash(
                            protocol.validate_authority(
                                _canonical_document(bytes(payload), "AUTHORITY")
                            )
                        )
                        != intent.get("authority_sha256")
                    ):
                        raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_CAS_SUBSTATE_INVALID")
                finally:
                    os.close(fd)
                os.unlink(Path(installer.AUTHORITY_REGISTRY_PATH).name, dir_fd=parent_fd)
                os.fsync(parent_fd)
                return OperationReconciliation("cleaned")
            if candidate is not None:
                raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_CAS_SUBSTATE_INVALID")
            if (
                active_info.st_dev != candidate_receipt.get("dev")
                or active_info.st_ino != candidate_receipt.get("ino")
                or active_info.st_nlink != 1
            ):
                raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_CAS_SUBSTATE_INVALID")
        finally:
            os.close(parent_fd)
        try:
            active = protocol.validate_authority(
                _canonical_document(
                    secure_read(Path(installer.AUTHORITY_REGISTRY_PATH), FilePolicy(0, 0, 0o444)),
                    "AUTHORITY",
                )
            )
        except (BrokerExecutorError, protocol.BrokerProtocolError) as error:
            raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_CAS_SUBSTATE_INVALID") from error
        if protocol.authority_hash(active) != intent.get("authority_sha256"):
            raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_CAS_SUBSTATE_INVALID")
        receipt = self._operation_receipt(
            "register-authority", "activate-prepared-authority-cas-last"
        )
        if receipt is None:
            raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_CAS_SUBSTATE_INVALID")
        return OperationReconciliation("owned-applied", receipt)

    def reconcile_operation(
        self,
        step_id: str,
        operation: str,
        intent: Mapping[str, object] | None,
    ) -> OperationReconciliation:
        """Adopt only an exact postimage, or prove that no effect occurred."""

        if operation == "activate-prepared-authority-cas-last":
            if not isinstance(intent, Mapping):
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_INTENT_MISSING", operation)
            return self.activation_receipt_from_intent(intent)
        if intent is None:
            # Operations without an intent are read-only verification units.
            return OperationReconciliation("not-applied")
        if (
            intent.get("kind") != "fixed-operation-intent"
            or intent.get("step_id") != step_id
            or intent.get("operation_id") != operation
            or not isinstance(intent.get("targets"), list)
            or not intent["targets"]
        ):
            raise BrokerExecutorError("MACOS_BACKEND_OPERATION_INTENT_INVALID", operation)
        targets = intent["targets"]
        cleaned_temp = False
        for target in targets:
            if isinstance(target, Mapping) and isinstance(target.get("temp_path"), str):
                cleaned_temp = self._reconcile_publication_temp(target, operation) or cleaned_temp
        absent = 0
        for target in targets:
            if not isinstance(target, Mapping):
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_INTENT_INVALID", operation)
            kind = target.get("kind")
            if kind in {"file", "path", "directory"}:
                path = target.get("path")
                if not isinstance(path, str):
                    raise BrokerExecutorError("MACOS_BACKEND_OPERATION_INTENT_INVALID", operation)
                if self._absent(path):
                    absent += 1
            elif kind == "launchd-registration":
                label = target.get("label")
                action = target.get("action")
                if (
                    not isinstance(label, str)
                    or action not in {"bootstrap", "kickstart"}
                    or not isinstance(target.get("program_arguments"), list)
                    or not isinstance(target.get("plist"), Mapping)
                ):
                    raise BrokerExecutorError("MACOS_BACKEND_OPERATION_INTENT_INVALID", operation)
                expected_precondition = (
                    "label-absent" if action == "bootstrap" else "registered-exact"
                )
                if target.get("precondition") != expected_precondition:
                    raise BrokerExecutorError("MACOS_BACKEND_OPERATION_INTENT_INVALID", operation)
                if action == "kickstart":
                    active_sha256 = target.get("active_authority_sha256")
                    if (
                        not _is_sha256_digest(active_sha256)
                        or self._active_authority_sha256() != active_sha256
                    ):
                        raise BrokerExecutorError(
                            "MACOS_BACKEND_LAUNCHD_OWNERSHIP_AMBIGUOUS", label
                        )
                if not self._launchd_registered(label):
                    if action == "kickstart":
                        return OperationReconciliation("not-applied")
                    absent += 1
                    continue
                plist = target.get("plist")
                plist_path = plist.get("path") if isinstance(plist, Mapping) else None
                try:
                    observed = self._launchd_job_receipt(
                        label,
                        str(plist_path),
                        require_live=action == "kickstart",
                    )
                except BrokerExecutorError as error:
                    if action == "kickstart" and error.code == "MACOS_BACKEND_SERVICE_NOT_LIVE":
                        return OperationReconciliation("not-applied")
                    # A generic present job after an unmatched START is not
                    # ours. Only the exact frozen marker, plist receipt and
                    # structural launchctl identity can reconcile success.
                    raise BrokerExecutorError(
                        "MACOS_BACKEND_LAUNCHD_OWNERSHIP_AMBIGUOUS",
                        label,
                    ) from error
                ignored = {"precondition", "action"}
                if action == "kickstart":
                    ignored.add("active_authority_sha256")
                expected = {key: value for key, value in target.items() if key not in ignored}
                if observed != expected:
                    raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_OWNERSHIP_AMBIGUOUS", label)
            elif kind == "directory-service-record":
                try:
                    self._operation_receipt(step_id, operation)
                except BrokerExecutorError as error:
                    if error.code == "MACOS_BACKEND_COMMAND_FAILED":
                        absent += 1
                    else:
                        raise
            else:
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_INTENT_INVALID", operation)
        if absent == len(targets):
            if any(
                target.get("precondition") not in {"absent", "absent-fixed-slot", "label-absent"}
                for target in targets
            ):
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_POSTIMAGE_AMBIGUOUS", operation)
            return OperationReconciliation("cleaned" if cleaned_temp else "not-applied")
        if absent:
            raise BrokerExecutorError("MACOS_BACKEND_OPERATION_POSTIMAGE_PARTIAL", operation)
        for target in targets:
            if target.get("kind") == "directory":
                try:
                    self._verify_directory(
                        str(target["path"]),
                        int(target["uid"]),
                        int(target["gid"]),
                        int(target["mode"]),
                    )
                except BrokerExecutorError:
                    if target.get("precondition") != "absent":
                        raise
                    self._repair_owned_directory(target, operation)
                if target.get("precondition") == "exact-existing":
                    return OperationReconciliation("not-applied")
        self._verify_recovered_operation_postimage(step_id, operation, intent)
        receipt = self._operation_receipt(step_id, operation)
        if receipt is None:
            return OperationReconciliation("not-applied")
        return OperationReconciliation("owned-applied", receipt)

    @staticmethod
    def _repair_owned_directory(target: Mapping[str, object], operation: str) -> None:
        path = Path(str(target["path"]))
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = -1
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            before = os.fstat(fd)
            if before.st_uid not in {0, int(target["uid"])} or before.st_mode & 0o022:
                raise BrokerExecutorError(
                    "MACOS_BACKEND_OPERATION_DIRECTORY_SUBSTATE_INVALID", operation
                )
            with os.scandir(fd) as entries:
                if next(entries, None) is not None:
                    raise BrokerExecutorError(
                        "MACOS_BACKEND_OPERATION_DIRECTORY_SUBSTATE_INVALID", operation
                    )
            os.fchown(fd, int(target["uid"]), int(target["gid"]))
            os.fchmod(fd, int(target["mode"]))
            os.fsync(fd)
            os.fsync(parent_fd)
            after = os.fstat(fd)
            named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
                or (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)
                or after.st_uid != target["uid"]
                or after.st_gid != target["gid"]
                or stat.S_IMODE(after.st_mode) != target["mode"]
            ):
                raise BrokerExecutorError(
                    "MACOS_BACKEND_OPERATION_DIRECTORY_SUBSTATE_INVALID", operation
                )
        finally:
            if fd >= 0:
                os.close(fd)
            os.close(parent_fd)

    @staticmethod
    def _repair_owned_empty_leaf(
        path: str, *, uid: int, gid: int, mode: int, operation: str
    ) -> None:
        target = Path(path)
        parent_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = -1
        try:
            fd = os.open(target.name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=parent_fd)
            before = os.fstat(fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size != 0
                or before.st_uid not in {0, uid}
                or before.st_mode & 0o002
            ):
                raise BrokerExecutorError(
                    "MACOS_BACKEND_OPERATION_LEAF_SUBSTATE_INVALID", operation
                )
            os.fchown(fd, uid, gid)
            os.fchmod(fd, mode)
            os.fsync(fd)
            os.fsync(parent_fd)
            after = os.fstat(fd)
            named = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
                or (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)
                or after.st_uid != uid
                or after.st_gid != gid
                or stat.S_IMODE(after.st_mode) != mode
            ):
                raise BrokerExecutorError(
                    "MACOS_BACKEND_OPERATION_LEAF_SUBSTATE_INVALID", operation
                )
        finally:
            if fd >= 0:
                os.close(fd)
            os.close(parent_fd)

    def _reconcile_publication_temp(
        self,
        target: Mapping[str, object],
        operation: str,
    ) -> bool:
        path = target.get("path")
        temp_path = target.get("temp_path")
        if not isinstance(path, str) or not isinstance(temp_path, str):
            raise BrokerExecutorError("MACOS_BACKEND_OPERATION_INTENT_INVALID", operation)
        expected_temp = self._publication_temp_path(path)
        if temp_path != expected_temp or Path(temp_path).parent != Path(path).parent:
            raise BrokerExecutorError("MACOS_BACKEND_OPERATION_INTENT_INVALID", operation)
        if self._absent(temp_path):
            return False
        parent_fd = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            temp_name = Path(temp_path).name
            temp_info = os.stat(temp_name, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(temp_info.st_mode) or temp_info.st_nlink not in {1, 2}:
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_TEMP_INVALID", operation)
            try:
                target_info = os.stat(Path(path).name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                target_info = None
            if target_info is None:
                if temp_info.st_nlink != 1 or temp_info.st_uid not in {
                    0,
                    int(target.get("expected", {}).get("uid", 0))
                    if isinstance(target.get("expected"), Mapping)
                    else 0,
                }:
                    raise BrokerExecutorError("MACOS_BACKEND_OPERATION_TEMP_INVALID", operation)
                os.unlink(temp_name, dir_fd=parent_fd)
                os.fsync(parent_fd)
                return True
            if (
                temp_info.st_nlink != 2
                or target_info.st_nlink != 2
                or (temp_info.st_dev, temp_info.st_ino) != (target_info.st_dev, target_info.st_ino)
            ):
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_TEMP_INVALID", operation)
            os.unlink(temp_name, dir_fd=parent_fd)
            os.fsync(parent_fd)
            return True
        finally:
            os.close(parent_fd)

    def _verify_recovered_operation_postimage(
        self,
        step_id: str,
        operation: str,
        intent: Mapping[str, object],
    ) -> None:
        base = operation.split("::", 1)[0]
        if "::file:" in operation:
            self._verify_target_row(self._row_for_unit(base, operation))
            return
        if "::directory:" in operation:
            return
        if operation == "install-root-owned-python-service-closure::bundle-manifest":
            raw = secure_read(
                Path(installer.INSTALL_BUNDLE_MANIFEST_PATH),
                FilePolicy(0, 0, 0o444),
                max_bytes=INSTALL_BUNDLE_MAX_BYTES,
            )
            if raw != installer.canonical_bundle_bytes(self._bundle):
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_POSTIMAGE_MISMATCH", operation)
            return
        if operation in {
            "precreate-ledger",
            "precreate-public-receipt-journal",
        }:
            path = (
                installer.BROKER_LEDGER_PATH
                if operation == "precreate-ledger"
                else installer.PUBLIC_RECEIPT_JOURNAL_PATH
            )
            target = intent["targets"][0]
            if target.get("precondition") == "absent":
                uid, gid, mode = (
                    (installer.BROKER_UID, installer.BROKER_GID, 0o600)
                    if operation == "precreate-ledger"
                    else (installer.BROKER_UID, installer.CALLER_GID, 0o640)
                )
                self._repair_owned_empty_leaf(
                    path, uid=uid, gid=gid, mode=mode, operation=operation
                )
            else:
                secure_read(
                    Path(path),
                    FilePolicy(
                        installer.BROKER_UID,
                        installer.BROKER_GID
                        if operation == "precreate-ledger"
                        else installer.CALLER_GID,
                        0o600 if operation == "precreate-ledger" else 0o640,
                    ),
                    max_bytes=1,
                )
            if os.stat(path, follow_symlinks=False).st_size != 0:
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_POSTIMAGE_MISMATCH", operation)
            return
        if operation == "precreate-anchor-genesis":
            expected = anchor_service.encode_genesis_log(self._genesis_anchor())
            if (
                secure_read(
                    Path(installer.ANCHOR_LOG_PATH),
                    FilePolicy(installer.ANCHOR_UID, installer.ANCHOR_GID, 0o600),
                    max_bytes=len(expected) + 1,
                )
                != expected
            ):
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_POSTIMAGE_MISMATCH", operation)
            return
        if operation == "create-exclusive-ed25519-seed-cryptography47":
            if (
                len(
                    secure_read(
                        Path(installer.SIGNING_KEY_PATH),
                        FilePolicy(0, installer.BROKER_GID, 0o440),
                        max_bytes=33,
                    )
                )
                != 32
            ):
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_POSTIMAGE_MISMATCH", operation)
            return
        if operation == "publish-public-key-registry-no-clobber":
            registry = _verification_registry(
                _canonical_document(
                    secure_read(Path(installer.PUBLIC_KEY_REGISTRY_PATH), FilePolicy(0, 0, 0o444)),
                    "PUBLIC_KEY_REGISTRY",
                )
            )
            seed = secure_read(
                Path(installer.SIGNING_KEY_PATH),
                FilePolicy(0, installer.BROKER_GID, 0o440),
                max_bytes=33,
            )
            public = protocol.ed25519.derive_public_key(seed)
            key_id = protocol.ed25519.mode_scoped_key_id(
                public, mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC
            )
            if registry != {key_id: public}:
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_POSTIMAGE_MISMATCH", operation)
            return
        if operation == "prepare-authority-candidate-no-clobber":
            authority = self._prepared_authority()
            expected = intent["targets"][0].get("expected_sha256")
            if protocol.authority_hash(authority) != expected:
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_POSTIMAGE_MISMATCH", operation)
            return
        if operation == "prepare-anchor-config-no-clobber":
            config = _canonical_document(
                secure_read(Path(installer.ANCHOR_CONFIG_PATH), FilePolicy(0, 0, 0o444)),
                "ANCHOR_CONFIG",
            )
            if config.get("active_authority_sha256") != intent["targets"][0].get(
                "active_authority_sha256"
            ):
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_POSTIMAGE_MISMATCH", operation)
            return
        if operation.startswith("install-") and operation.endswith("-plist"):
            role = {
                "install-launcher-plist": "launcher-plist",
                "install-anchor-plist": "anchor-plist",
                "install-broker-plist": "broker-plist",
            }[operation]
            self._verify_target_row(self._install_rows[installer.EXPECTED_ARTIFACT_PATHS[role]])
            return
        if operation.startswith(
            ("create-group-record-", "set-group-primary-gid-", "create-user-record-", "set-user-")
        ):
            # The fixed-slot absence intent is durable and the transition
            # journal is held exclusively.  A readable postimage can therefore
            # be adopted; later operations on the same record supersede its
            # earlier raw digest receipt.
            self._operation_receipt(step_id, operation)
            return
        if operation in self._LAUNCHD_BOOTSTRAP_OPERATIONS:
            label, _plist = self._LAUNCHD_BOOTSTRAP_OPERATIONS[operation]
            if not self._launchd_registered(label):
                raise BrokerExecutorError("MACOS_BACKEND_OPERATION_POSTIMAGE_MISMATCH", operation)
            return
        if operation in self._LAUNCHD_KICKSTART_OPERATIONS:
            label, plist = self._LAUNCHD_KICKSTART_OPERATIONS[operation]
            self._launchd_job_receipt(label, plist, require_live=True)
            return

    def _measure_authority_roster(
        self,
    ) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
        measured_by_role: dict[str, dict[str, object]] = {}
        for role, artifact in self._artifacts.items():
            row = self._verify_target_row(self._install_rows[str(artifact["install_path"])])
            measured_by_role[role] = row
        measured_all = [
            self._verify_target_row(row)
            for row in sorted(self._install_rows.values(), key=lambda item: str(item["path"]))
        ]
        live_content = installer.release_content_roster_digest(measured_all)
        if live_content != self._bundle["release_content_roster_sha256"]:
            raise BrokerExecutorError("MACOS_BACKEND_RELEASE_CONTENT_REMEASURE_MISMATCH")
        authorized_paths = set(self._bundle["authority_roster_paths"])
        authority_rows: list[dict[str, object]] = []
        for measured in measured_all:
            if str(measured["path"]) not in authorized_paths:
                continue
            row = dict(measured)
            row["path"] = installer.authority_logical_path(str(measured["path"]))
            authority_rows.append(row)
        if {
            str(row["path"]) for row in measured_all if str(row["path"]) in authorized_paths
        } != authorized_paths:
            raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_CLOSURE_INCOMPLETE")
        authority_rows.sort(key=lambda row: str(row["path"]))
        return authority_rows, measured_by_role

    def _build_authority(self) -> dict[str, object]:
        roster, measured = self._measure_authority_roster()
        seed = secure_read(
            Path(installer.SIGNING_KEY_PATH), FilePolicy(0, installer.BROKER_GID, 0o440)
        )
        public_key = protocol.ed25519.derive_public_key(seed)
        code_identity = {
            protocol.ROLE_DIGEST_FIELD[role]: measured[role]["sha256"]
            for role in protocol.INSTALLED_CODE_ROLES
        }
        code_paths = {
            role: installer.AUTHORITY_LOGICAL_PATHS[role] for role in protocol.INSTALLED_CODE_ROLES
        }
        parameters = {"NODE_SHA256": installer.NODE_SHA256}
        authority = {
            "schema_version": 1,
            "kind": protocol.KIND_AUTHORITY,
            "authority_id": installer.AUTHORITY_ID,
            "mode": protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
            "signing": {
                "algorithm": protocol.PRODUCTION_ALGORITHM,
                "key_id": protocol.ed25519.mode_scoped_key_id(
                    public_key, mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC
                ),
                "public_key": protocol.ed25519.encode_public_key(public_key),
            },
            "broker_identity": {
                "user": installer.BROKER_PRINCIPAL,
                "uid": installer.BROKER_UID,
                "gid": installer.BROKER_GID,
            },
            "runner_identity": {
                "user": installer.RUNNER_PRINCIPAL,
                "uid": installer.RUNNER_UID,
                "gid": installer.RUNNER_GID,
            },
            "launcher_identity": {"user": "root", "uid": 0, "gid": 0},
            "installed_code_identity": code_identity,
            "installed_code_paths": code_paths,
            "installed_code_roster": roster,
            "policy_identity": {
                "template_sha256": self._POLICY_TEMPLATE_SHA256,
                "parameters": parameters,
                "resolved_sha256": protocol.policy_hash(self._POLICY_TEMPLATE_SHA256, parameters),
            },
            "release_identity": {
                "release_id": installer.RELEASE_ID,
                "ancestry_root_sha256": protocol.release_ancestry_hash(
                    installer.RELEASE_ID, roster
                ),
            },
        }
        return protocol.validate_authority(authority)

    @staticmethod
    def _genesis_anchor() -> anchor_service.ConsumerAnchor:
        return anchor_service.ConsumerAnchor(
            instance_id=installer.ANCHOR_INSTANCE_ID, revision=0, heads=()
        )

    def _prepare_authority_candidate(self) -> None:
        authority = self._build_authority()
        self._write_exclusive(
            Path(installer.AUTHORITY_CANDIDATE_PATH),
            protocol.canonical_bytes(authority),
            uid=0,
            gid=0,
            mode=0o444,
        )

    def _prepare_anchor_config(self) -> None:
        authority = self._prepared_authority()
        authority_sha256 = protocol.authority_hash(authority)
        signing = authority["signing"]
        release = authority["release_identity"]
        config = {
            "schema_version": anchor_service.ANCHOR_SERVICE_SCHEMA_VERSION,
            "kind": "w3-protected-anchor-installed-config",
            "active_authority_path": installer.AUTHORITY_REGISTRY_PATH,
            "active_authority_sha256": authority_sha256,
            "genesis_anchor_sha256": self._genesis_anchor().digest(),
            "anchor_uid": installer.ANCHOR_UID,
            "anchor_gid": installer.ANCHOR_GID,
            "caller_uid": installer.CALLER_UID,
            "caller_gid": installer.CALLER_GID,
            "authorities": [authority],
            "key_epochs": [
                {
                    "mode": authority["mode"],
                    "algorithm": signing["algorithm"],
                    "key_id": signing["key_id"],
                    "public_key": signing["public_key"],
                    "revocation_high_water": None,
                }
            ],
            "releases": [
                {
                    "authority_sha256": authority_sha256,
                    "release_id": release["release_id"],
                    "release_sha256": release["ancestry_root_sha256"],
                    "retired_after_receipt_sequence": None,
                }
            ],
            "registered_policy_sha256s": [authority["policy_identity"]["resolved_sha256"]],
        }
        self._write_exclusive(
            Path(installer.ANCHOR_CONFIG_PATH),
            protocol.canonical_bytes(config),
            uid=0,
            gid=0,
            mode=0o444,
        )

    def _prepared_authority(self) -> dict[str, object]:
        return protocol.validate_authority(
            _canonical_document(
                secure_read(Path(installer.AUTHORITY_CANDIDATE_PATH), FilePolicy(0, 0, 0o444)),
                "AUTHORITY_CANDIDATE",
            )
        )

    def _activate_authority_cas(self) -> None:
        candidate = Path(installer.AUTHORITY_CANDIDATE_PATH)
        active = Path(installer.AUTHORITY_REGISTRY_PATH)
        authority = self._prepared_authority()
        if not self._absent(str(active)):
            raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_ALREADY_ACTIVE")
        parent_fd = os.open(candidate.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        linked = False
        try:
            os.link(
                candidate.name,
                active.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            linked = True
            os.fsync(parent_fd)
            os.unlink(candidate.name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        if not linked:
            raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_CAS_FAILED")
        installed = protocol.validate_authority(
            _canonical_document(secure_read(active, FilePolicy(0, 0, 0o444)), "AUTHORITY")
        )
        if protocol.authority_hash(installed) != protocol.authority_hash(authority):
            raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_CAS_MISMATCH")

    def _verify_service_live(self, label: str) -> None:
        plist = {
            installer.LAUNCHER_PLIST_LABEL: installer.EXPECTED_ARTIFACT_PATHS["launcher-plist"],
            installer.ANCHOR_PLIST_LABEL: installer.EXPECTED_ARTIFACT_PATHS["anchor-plist"],
            installer.BROKER_PLIST_LABEL: installer.EXPECTED_ARTIFACT_PATHS["broker-plist"],
        }.get(label)
        if plist is None:
            raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_LABEL_INVALID", label)
        try:
            self._launchd_job_receipt(label, plist, require_live=True)
        except BrokerExecutorError as error:
            if error.code == "MACOS_BACKEND_SERVICE_NOT_LIVE":
                raise
            raise BrokerExecutorError("MACOS_BACKEND_SERVICE_NOT_LIVE", label) from error

    def _verify_durable_state_semantics(self) -> set[str]:
        """Replay ledger, public receipt journal and protected anchor read-only."""

        try:
            installed_anchor = anchor_service._installed_service()
            ledger_path = Path(installer.BROKER_LEDGER_PATH)
            self._verify_root_owned_ancestry(ledger_path)
            ledger_fd = os.open(ledger_path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                before = os.fstat(ledger_fd)
                named = os.stat(ledger_path, follow_symlinks=False)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_uid != installer.BROKER_UID
                    or before.st_gid != installer.BROKER_GID
                    or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_nlink != 1
                    or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)
                ):
                    raise BrokerExecutorError("MACOS_BACKEND_FINAL_LEDGER_METADATA_INVALID")
                records = broker_core._read_records(ledger_fd, repair_torn_tail=False)
                state = broker_core._state_from_records(
                    records,
                    receipt_verifier=installed_anchor._verifier.verify_only,
                )
                after = os.fstat(ledger_fd)
                named_after = os.stat(ledger_path, follow_symlinks=False)
                identity = (
                    "st_dev",
                    "st_ino",
                    "st_mode",
                    "st_uid",
                    "st_gid",
                    "st_nlink",
                    "st_size",
                )
                if any(
                    getattr(before, field) != getattr(after, field) for field in identity
                ) or any(
                    getattr(before, field) != getattr(named_after, field) for field in identity
                ):
                    raise BrokerExecutorError("MACOS_BACKEND_FINAL_LEDGER_IDENTITY_CHANGED")
            finally:
                os.close(ledger_fd)

            ledger_receipts = sorted(
                (dict(row["receipt"]) for row in state.receipts_by_nonce.values()),
                key=lambda receipt: int(receipt["receipt_sequence"]),
            )
            public_raw = secure_read(
                Path(installer.PUBLIC_RECEIPT_JOURNAL_PATH),
                FilePolicy(installer.BROKER_UID, installer.CALLER_GID, 0o640),
                max_bytes=broker_client.PROTECTED_RECEIPT_JOURNAL_MAX_BYTES,
            )
            if public_raw:
                public_receipts = list(broker_client._read_protected_receipt_journal(public_raw))
            else:
                public_receipts = []
            if len(public_receipts) != len(ledger_receipts):
                raise BrokerExecutorError("MACOS_BACKEND_FINAL_PUBLIC_LEDGER_COUNT_MISMATCH")
            previous = protocol.GENESIS_RECEIPT_DIGEST
            for sequence, (public, durable) in enumerate(
                zip(public_receipts, ledger_receipts, strict=True), start=1
            ):
                verified = installed_anchor._verifier.verify_only(public)
                if (
                    verified != durable
                    or int(verified["receipt_sequence"]) != sequence
                    or verified["previous_receipt_sha256"] != previous
                    or protocol.canonical_bytes(verified) != protocol.canonical_bytes(durable)
                ):
                    raise BrokerExecutorError("MACOS_BACKEND_FINAL_PUBLIC_LEDGER_RECEIPT_MISMATCH")
                previous = protocol.receipt_hash(verified)
            if (
                state.last_receipt_sequence != len(ledger_receipts)
                or state.last_receipt_sha256 != previous
            ):
                raise BrokerExecutorError("MACOS_BACKEND_FINAL_LEDGER_TAIL_MISMATCH")

            with installed_anchor._locked_log() as (anchor_fd, _parent_fd):
                anchor_records = anchor_service._read_records(anchor_fd)
                current_anchor, _last_advance = installed_anchor._recover(anchor_records)
            head = current_anchor.head_for(protocol.AUTHORITY_ID)
            if not ledger_receipts:
                if current_anchor.revision != 0 or current_anchor.heads or head is not None:
                    raise BrokerExecutorError("MACOS_BACKEND_FINAL_ANCHOR_LEDGER_MISMATCH")
            elif (
                current_anchor.revision != len(ledger_receipts)
                or len(current_anchor.heads) != 1
                or head is None
                or head.receipt_sequence != len(ledger_receipts)
                or head.receipt_sha256 != previous
            ):
                raise BrokerExecutorError("MACOS_BACKEND_FINAL_ANCHOR_LEDGER_MISMATCH")
            expected_publications: set[str] = set()
            for receipt in ledger_receipts:
                request_hash = str(receipt["request"]["request_hash"])[7:]
                name = f"{receipt['attempt_sequence']}-{request_hash}.json"
                path = str(Path(installer.PUBLICATION_ACTIVE) / name)
                if path in expected_publications:
                    raise BrokerExecutorError("MACOS_BACKEND_FINAL_PUBLICATION_DUPLICATE")
                expected_publications.add(path)
                info, digest = self._hash_file(Path(path))
                publication = receipt["output"]["publication"]
                if (
                    info.st_uid != installer.BROKER_UID
                    or info.st_gid != installer.BROKER_GID
                    or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_nlink != 1
                    or info.st_size != publication["size"]
                    or digest != publication["sha256"]
                ):
                    raise BrokerExecutorError("MACOS_BACKEND_FINAL_PUBLICATION_MISMATCH", path)
            publication_files, publication_directories = self._walk_paths(
                installer.PUBLICATION_ACTIVE
            )
            if (
                publication_directories != {installer.PUBLICATION_ACTIVE}
                or publication_files != expected_publications
            ):
                raise BrokerExecutorError("MACOS_BACKEND_FINAL_PUBLICATION_SET_MISMATCH")
            run_files, run_directories = self._walk_paths(installer.RUNS_ACTIVE)
            if run_directories != {installer.RUNS_ACTIVE} or run_files:
                raise BrokerExecutorError("MACOS_BACKEND_FINAL_RUN_ROOT_NOT_EMPTY")
            return expected_publications
        except BrokerExecutorError:
            raise
        except Exception as error:
            raise BrokerExecutorError(
                "MACOS_BACKEND_FINAL_DURABLE_REPLAY_FAILED", type(error).__name__
            ) from error

    @staticmethod
    def _verify_final_key_binding(authority: Mapping[str, object]) -> None:
        seed = secure_read(
            Path(installer.SIGNING_KEY_PATH),
            FilePolicy(0, installer.BROKER_GID, 0o440),
        )
        registry = _verification_registry(
            _canonical_document(
                secure_read(Path(installer.PUBLIC_KEY_REGISTRY_PATH), FilePolicy(0, 0, 0o444)),
                "PUBLIC_KEY_REGISTRY",
            )
        )
        derived_public_key = protocol.ed25519.derive_public_key(seed)
        derived_key_id = protocol.ed25519.mode_scoped_key_id(
            derived_public_key,
            mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
        )
        if (
            set(registry) != {derived_key_id}
            or registry[derived_key_id] != derived_public_key
            or authority.get("signing")
            != {
                "algorithm": protocol.PRODUCTION_ALGORITHM,
                "key_id": derived_key_id,
                "public_key": protocol.ed25519.encode_public_key(derived_public_key),
            }
        ):
            raise BrokerExecutorError("MACOS_BACKEND_FINAL_KEY_REGISTRY_MISMATCH")

    def verify_final_postconditions(self) -> Mapping[str, object]:
        raw = secure_read(Path(installer.AUTHORITY_REGISTRY_PATH), FilePolicy(0, 0, 0o444))
        authority = protocol.validate_authority(_canonical_document(raw, "AUTHORITY"))
        roster, _measured = self._measure_authority_roster()
        if authority["installed_code_roster"] != roster:
            raise BrokerExecutorError("MACOS_BACKEND_FINAL_ROSTER_MISMATCH")
        expected_ancestry = protocol.release_ancestry_hash(installer.RELEASE_ID, roster)
        if authority["release_identity"] != {
            "release_id": installer.RELEASE_ID,
            "ancestry_root_sha256": expected_ancestry,
        }:
            raise BrokerExecutorError("MACOS_BACKEND_FINAL_ANCESTRY_MISMATCH")
        config = _canonical_document(
            secure_read(Path(installer.ANCHOR_CONFIG_PATH), FilePolicy(0, 0, 0o444)),
            "ANCHOR_CONFIG",
        )
        expected_config_fields = {
            "schema_version",
            "kind",
            "active_authority_path",
            "active_authority_sha256",
            "genesis_anchor_sha256",
            "anchor_uid",
            "anchor_gid",
            "caller_uid",
            "caller_gid",
            "authorities",
            "key_epochs",
            "releases",
            "registered_policy_sha256s",
        }
        if (
            set(config) != expected_config_fields
            or config["active_authority_path"] != installer.AUTHORITY_REGISTRY_PATH
            or config["active_authority_sha256"] != protocol.authority_hash(authority)
            or config["authorities"] != [authority]
            or config["genesis_anchor_sha256"] != self._genesis_anchor().digest()
            or config["anchor_uid"] != installer.ANCHOR_UID
            or config["anchor_gid"] != installer.ANCHOR_GID
            or config["caller_uid"] != installer.CALLER_UID
            or config["caller_gid"] != installer.CALLER_GID
        ):
            raise BrokerExecutorError("MACOS_BACKEND_FINAL_ANCHOR_CONFIG_MISMATCH")
        if not self._absent(installer.AUTHORITY_CANDIDATE_PATH):
            raise BrokerExecutorError("MACOS_BACKEND_FINAL_AUTHORITY_CANDIDATE_RETAINED")
        self._verify_final_key_binding(authority)
        durable_specs = {
            installer.BROKER_LEDGER_PATH: (installer.BROKER_UID, installer.BROKER_GID, 0o600),
            installer.PUBLIC_RECEIPT_JOURNAL_PATH: (
                installer.BROKER_UID,
                installer.CALLER_GID,
                0o640,
            ),
            installer.ANCHOR_LOG_PATH: (installer.ANCHOR_UID, installer.ANCHOR_GID, 0o600),
            installer.INSTALL_TRANSITION_JOURNAL_PATH: (0, 0, 0o600),
        }
        for path, (uid, gid, mode) in durable_specs.items():
            info = os.stat(path, follow_symlinks=False)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != uid
                or info.st_gid != gid
                or stat.S_IMODE(info.st_mode) != mode
            ):
                raise BrokerExecutorError("MACOS_BACKEND_FINAL_DURABLE_LEAF_MISMATCH", path)
        expected_genesis = anchor_service.encode_genesis_log(self._genesis_anchor())
        anchor_raw = secure_read(
            Path(installer.ANCHOR_LOG_PATH),
            FilePolicy(installer.ANCHOR_UID, installer.ANCHOR_GID, 0o600),
            max_bytes=64 * 1024 * 1024,
        )
        if not anchor_raw:
            raise BrokerExecutorError("MACOS_BACKEND_FINAL_ANCHOR_GENESIS_MISSING")
        if (
            not secure_read(
                Path(installer.BROKER_LEDGER_PATH),
                FilePolicy(installer.BROKER_UID, installer.BROKER_GID, 0o600),
                max_bytes=64 * 1024 * 1024,
            )
            and anchor_raw != expected_genesis
        ):
            raise BrokerExecutorError("MACOS_BACKEND_FINAL_ANCHOR_GENESIS_MISMATCH")
        dynamic_publications = self._verify_durable_state_semantics()
        for path, uid, gid, mode in (
            (installer.PUBLICATION_ACTIVE, installer.BROKER_UID, installer.BROKER_GID, 0o700),
            (installer.RUNS_ACTIVE, installer.RUNNER_UID, installer.RUNNER_GID, 0o700),
        ):
            self._verify_directory(path, uid, gid, mode)
        self._verify_managed_tree_exact(complete=True, dynamic_publications=dynamic_publications)
        for label in (
            installer.LAUNCHER_PLIST_LABEL,
            installer.ANCHOR_PLIST_LABEL,
            installer.BROKER_PLIST_LABEL,
        ):
            self._verify_service_live(label)
        self._applied_evidence = {
            "authority_sha256": protocol.authority_hash(authority),
            "release_ancestry_sha256": expected_ancestry,
            "release_content_roster_sha256": self._bundle["release_content_roster_sha256"],
        }
        return dict(self._applied_evidence)

    def _perform(self, operation: str, step_id: str) -> None:
        if operation in {
            "verify-canonical-plan",
            "verify-frozen-bundle",
            "verify-complete-source-install-rosters",
        }:
            installer.validate_bundle_manifest(self._bundle, require_frozen=True)
            return
        if operation == "verify-caller-account-501-20":
            self._account_row("caller")
            return
        if operation == "verify-service-name-uid-gid-slots-free":
            for role in ("broker", "runner", "anchor"):
                self._identity_slot_free(role)
            return
        if operation == "preflight-managed-target-conflicts-and-staged-closure":
            self._preflight_managed_targets()
            return
        identity_roles = {"metisbroker": "broker", "metisrunner": "runner", "metisanchor": "anchor"}
        for role in identity_roles.values():
            principal = installer.FIXED_PRINCIPALS[role]
            if operation == f"create-group-record-{principal['gid']}":
                self._group_slot_free(role)
                self._run(("/usr/bin/dscl", ".", "-create", f"/Groups/{principal['group']}"))
                return
            if operation == f"set-group-primary-gid-{principal['gid']}":
                self._run(
                    (
                        "/usr/bin/dscl",
                        ".",
                        "-create",
                        f"/Groups/{principal['group']}",
                        "PrimaryGroupID",
                        str(principal["gid"]),
                    )
                )
                return
            if operation == f"create-user-record-{principal['uid']}":
                self._user_slot_free(role)
                self._run(("/usr/bin/dscl", ".", "-create", f"/Users/{principal['name']}"))
                return
            if operation == f"set-user-unique-id-{principal['uid']}":
                self._run(
                    (
                        "/usr/bin/dscl",
                        ".",
                        "-create",
                        f"/Users/{principal['name']}",
                        "UniqueID",
                        str(principal["uid"]),
                    )
                )
                return
            user_fields = {
                f"set-user-primary-gid-{principal['uid']}": (
                    "PrimaryGroupID",
                    str(principal["gid"]),
                ),
                f"set-user-home-{principal['uid']}": ("NFSHomeDirectory", "/var/empty"),
                f"set-user-shell-{principal['uid']}": ("UserShell", "/usr/bin/false"),
            }
            if operation in user_fields:
                user = f"/Users/{principal['name']}"
                key, value = user_fields[operation]
                self._run(("/usr/bin/dscl", ".", "-create", user, key, value))
                return
            if operation == f"verify-user-group-{principal['uid']}":
                self._account_row(role)
                return
        if operation == "install-root-owned-python-service-closure":
            self._install_step_rows("install-broker-code")
            self._write_exclusive(
                Path(installer.INSTALL_BUNDLE_MANIFEST_PATH),
                installer.canonical_bundle_bytes(self._bundle),
                uid=0,
                gid=0,
                mode=0o444,
            )
            return
        if operation == "install-fixed-directory-roster":
            for path, (uid, gid, mode) in sorted(
                self._directories.items(), key=lambda item: (item[0].count("/"), item[0])
            ):
                self._ensure_dir(path, uid, gid, mode)
            return
        if operation == "install-distinct-broker-anchor-shims":
            for role in ("broker-socket-shim", "anchor-socket-shim"):
                self._verify_target_row(self._install_rows[installer.EXPECTED_ARTIFACT_PATHS[role]])
            return
        if operation == "verify-fixed-python-module-entrypoints":
            for path in installer.REQUIRED_SITE_PACKAGE_PATHS:
                self._verify_target_row(self._install_rows[path])
            return
        if operation == "install-cpython-3.13.3-symlink-free":
            self._install_step_rows("install-runtime")
            return
        if operation in {"install-cryptography-47-cffi-pycparser", "verify-runtime-roster"}:
            self._verify_step_rows("install-runtime")
            return
        if operation == "install-node-v22.22.3":
            self._verify_target_row(self._install_rows[installer.EXPECTED_ARTIFACT_PATHS["node"]])
            return
        if operation == "install-stable-release-slot":
            self._ensure_dir(installer.RELEASE_ROOT, 0, 0, 0o755)
            return
        if operation == "install-public-capsule":
            self._install_step_rows("install-release")
            return
        if operation == "install-concrete-seatbelt-policy":
            policy = Path(installer.EXPECTED_ARTIFACT_PATHS["policy"])
            installer.validate_concrete_policy_bytes(policy.read_bytes())
            return
        if operation == "verify-release-content-roster":
            self._verify_step_rows("install-release")
            return
        if operation == "install-privileged-launcher":
            self._install_step_rows("install-launcher")
            return
        if operation == "verify-launcher-fixed-macros-and-hash":
            self._verify_step_rows("install-launcher")
            return
        leaf_operations = {
            "precreate-ledger": (
                installer.BROKER_LEDGER_PATH,
                installer.BROKER_UID,
                installer.BROKER_GID,
                0o600,
                False,
            ),
            "precreate-public-receipt-journal": (
                installer.PUBLIC_RECEIPT_JOURNAL_PATH,
                installer.BROKER_UID,
                installer.CALLER_GID,
                0o640,
                False,
            ),
            "precreate-anchor-genesis": (
                installer.ANCHOR_LOG_PATH,
                installer.ANCHOR_UID,
                installer.ANCHOR_GID,
                0o600,
                False,
            ),
            "precreate-publication-active": (
                installer.PUBLICATION_ACTIVE,
                installer.BROKER_UID,
                installer.BROKER_GID,
                0o700,
                True,
            ),
            "precreate-runs-active": (
                installer.RUNS_ACTIVE,
                installer.RUNNER_UID,
                installer.RUNNER_GID,
                0o700,
                True,
            ),
        }
        if operation == "verify-bootstrap-install-journal":
            self._measure_receipt_path(installer.INSTALL_TRANSITION_JOURNAL_PATH)
            return
        if operation in leaf_operations:
            if operation == "precreate-anchor-genesis":
                genesis = anchor_service.encode_genesis_log(self._genesis_anchor())
                if self._absent(installer.ANCHOR_LOG_PATH):
                    self._write_exclusive(
                        Path(installer.ANCHOR_LOG_PATH),
                        genesis,
                        uid=installer.ANCHOR_UID,
                        gid=installer.ANCHOR_GID,
                        mode=0o600,
                    )
                elif (
                    secure_read(
                        Path(installer.ANCHOR_LOG_PATH),
                        FilePolicy(installer.ANCHOR_UID, installer.ANCHOR_GID, 0o600),
                        max_bytes=len(genesis) + 1,
                    )
                    != genesis
                ):
                    raise BrokerExecutorError("MACOS_BACKEND_RETRY_ANCHOR_NOT_GENESIS")
            else:
                leaf_path = leaf_operations[operation][0]
                if not self._absent(leaf_path):
                    if operation in {"precreate-ledger", "precreate-public-receipt-journal"}:
                        self._verify_retained_retry_state()
                    else:
                        raise BrokerExecutorError(
                            "MACOS_BACKEND_DYNAMIC_TARGET_PREEXISTS", leaf_path
                        )
                else:
                    self._precreate_leaf(
                        leaf_path,
                        uid=leaf_operations[operation][1],
                        gid=leaf_operations[operation][2],
                        mode=leaf_operations[operation][3],
                        directory=leaf_operations[operation][4],
                    )
            return
        if operation == "verify-run-parent-active-inodes":
            self._ensure_dir(installer.RUNS_PARENT, 0, 0, 0o711)
            self._measure_receipt_path(installer.RUNS_ACTIVE)
            return
        if operation in {"verify-complete-installed-roster", "verify-owner-group-mode-link-inodes"}:
            for row in self._install_rows.values():
                self._verify_target_row(row)
            return
        if operation == "verify-no-extra-missing-or-symlink":
            self._verify_managed_tree_exact(complete=False)
            return
        if operation == "create-exclusive-ed25519-seed-cryptography47":
            self._create_signing_seed()
            return
        if operation == "publish-public-key-registry-no-clobber":
            self._publish_public_key_registry()
            return
        if operation == "prepare-authority-candidate-no-clobber":
            self._prepare_authority_candidate()
            return
        if operation == "prepare-anchor-config-no-clobber":
            self._prepare_anchor_config()
            return
        if operation == "verify-prepared-authority-config-key-binding":
            _verification_registry(
                _canonical_document(
                    secure_read(Path(installer.PUBLIC_KEY_REGISTRY_PATH), FilePolicy(0, 0, 0o444)),
                    "PUBLIC_KEY_REGISTRY",
                )
            )
            authority = self._prepared_authority()
            config = _canonical_document(
                secure_read(Path(installer.ANCHOR_CONFIG_PATH), FilePolicy(0, 0, 0o444)),
                "ANCHOR_CONFIG",
            )
            if config["active_authority_sha256"] != protocol.authority_hash(authority) or config[
                "authorities"
            ] != [authority]:
                raise BrokerExecutorError("MACOS_BACKEND_PREPARED_AUTHORITY_CONFIG_MISMATCH")
            return
        if operation == "install-launcher-plist":
            self._install_row(
                self._install_rows[installer.EXPECTED_ARTIFACT_PATHS["launcher-plist"]]
            )
            return
        if operation == "install-anchor-plist":
            self._install_row(self._install_rows[installer.EXPECTED_ARTIFACT_PATHS["anchor-plist"]])
            return
        if operation == "install-broker-plist":
            self._install_row(self._install_rows[installer.EXPECTED_ARTIFACT_PATHS["broker-plist"]])
            return
        if operation == "verify-three-plists-and-socket-owners":
            self._verify_step_rows("install-launchd-plists")
            return
        service_operations = {
            **{
                operation_id: ("bootstrap", *identity)
                for operation_id, identity in self._LAUNCHD_BOOTSTRAP_OPERATIONS.items()
            },
            **{
                operation_id: ("kickstart", *identity)
                for operation_id, identity in self._LAUNCHD_KICKSTART_OPERATIONS.items()
            },
            "verify-launcher-service": (
                "registered",
                installer.LAUNCHER_PLIST_LABEL,
                installer.EXPECTED_ARTIFACT_PATHS["launcher-plist"],
            ),
            "verify-anchor-job-authority-gated": (
                "gated",
                installer.ANCHOR_PLIST_LABEL,
                installer.EXPECTED_ARTIFACT_PATHS["anchor-plist"],
            ),
            "verify-broker-job-authority-gated": (
                "gated",
                installer.BROKER_PLIST_LABEL,
                installer.EXPECTED_ARTIFACT_PATHS["broker-plist"],
            ),
        }
        if operation in service_operations:
            action, label, plist = service_operations[operation]
            if action == "bootstrap":
                if self._launchd_registered(label):
                    raise BrokerExecutorError("MACOS_BACKEND_LAUNCHD_LABEL_PREEXISTS", label)
                self._run(("/bin/launchctl", "bootstrap", "system", plist))
            elif action == "registered":
                self._launchd_job_receipt(label, plist)
            elif action == "gated":
                if not self._absent(installer.AUTHORITY_REGISTRY_PATH):
                    raise BrokerExecutorError("MACOS_BACKEND_AUTHORITY_ACTIVATED_TOO_EARLY", label)
                self._launchd_job_receipt(label, plist)
            else:
                active_sha256 = self._active_authority_sha256()
                pending = self._pending_operation_intents.get((step_id, operation))
                targets = pending.get("targets") if isinstance(pending, Mapping) else None
                if (
                    not isinstance(targets, list)
                    or len(targets) != 1
                    or not isinstance(targets[0], Mapping)
                ):
                    raise BrokerExecutorError("MACOS_BACKEND_OPERATION_INTENT_MISSING", operation)
                expected_sha256 = targets[0].get("active_authority_sha256")
                if active_sha256 != expected_sha256:
                    raise BrokerExecutorError("MACOS_BACKEND_ACTIVE_AUTHORITY_CHANGED", label)
                self._launchd_job_receipt(label, plist)
                self._run(("/bin/launchctl", "kickstart", f"system/{label}"))
                self._poll_launchd_live(label, plist)
            return
        if operation == "activate-prepared-authority-cas-last":
            self._activate_authority_cas()
            return
        if operation == "verify-authority-config-and-services-live":
            self.verify_final_postconditions()
            return
        raise BrokerExecutorError("MACOS_BACKEND_OPERATION_UNIMPLEMENTED", operation)

    def apply(self, step: Mapping[str, object]) -> BackendEffect:
        step_id = str(step.get("id"))
        operations = installer.MACOS_BACKEND_OPERATION_ROSTER.get(step_id)
        if operations is None or not operations:
            raise BrokerExecutorError("MACOS_BACKEND_STEP_INVALID", step_id)
        for operation in operations:
            self._perform(operation, step_id)
        return BackendEffect(len(operations), self._ownership_receipt(step_id))

    @staticmethod
    def _receipt_row_matches_path(
        row: Mapping[str, object],
        path: str,
        *,
        allow_quarantined_metadata: bool = False,
    ) -> bool:
        try:
            info = os.stat(path, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if row.get("kind") == "file":
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", path)
            expected_metadata = (row.get("uid"), row.get("gid"), row.get("mode"))
            actual_metadata = (info.st_uid, info.st_gid, info.st_mode)
            quarantined_metadata = (0, 0, stat.S_IFREG | 0o400)
            if actual_metadata != expected_metadata and not (
                allow_quarantined_metadata and actual_metadata == quarantined_metadata
            ):
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", path)
            if row.get("dev") != info.st_dev or row.get("ino") != info.st_ino:
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", path)
            if "sha256" in row:
                measured, digest = MacOSInstallBackend._hash_file(Path(path))
                if measured.st_size != row.get("size") or digest != row.get("sha256"):
                    raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", path)
            return True
        if row.get("kind") == "directory":
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != row.get("uid")
                or info.st_gid != row.get("gid")
                or info.st_mode != row.get("mode")
                or info.st_dev != row.get("dev")
                or info.st_ino != row.get("ino")
            ):
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", path)
            return True
        raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_RECEIPT_INVALID", path)

    @staticmethod
    def _open_receipt_owned_file(
        row: Mapping[str, object],
        path: str,
        *,
        allow_quarantined_metadata: bool = False,
    ) -> tuple[int, int, bytes]:
        """Open and bind an owned rollback leaf to its receipt and parent dirfd."""

        target = Path(path)
        parent_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = -1
        try:
            fd = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
            info = os.fstat(fd)
            named = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
            expected_metadata = (row.get("uid"), row.get("gid"), row.get("mode"))
            actual_metadata = (info.st_uid, info.st_gid, info.st_mode)
            quarantined_metadata = (0, 0, stat.S_IFREG | 0o400)
            if (
                row.get("kind") != "file"
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (info.st_dev, info.st_ino) != (row.get("dev"), row.get("ino"))
                or (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino)
                or actual_metadata != expected_metadata
                and not (allow_quarantined_metadata and actual_metadata == quarantined_metadata)
            ):
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", path)
            expected_size = row.get("size")
            expected_digest = row.get("sha256")
            if type(expected_size) is not int or not isinstance(expected_digest, str):
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_RECEIPT_INVALID", path)
            payload = bytearray()
            while len(payload) <= expected_size:
                chunk = os.read(fd, min(1024 * 1024, expected_size + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
            if (
                len(payload) != expected_size
                or info.st_size != expected_size
                or "sha256:" + hashlib.sha256(payload).hexdigest() != expected_digest
            ):
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", path)
            return parent_fd, fd, bytes(payload)
        except Exception:
            if fd >= 0:
                os.close(fd)
            os.close(parent_fd)
            raise

    @staticmethod
    def _recheck_held_owned_file(
        row: Mapping[str, object],
        path: str,
        parent_fd: int,
        fd: int,
        payload: bytes,
        *,
        uid: int,
        gid: int,
        mode: int,
    ) -> None:
        target = Path(path)
        os.lseek(fd, 0, os.SEEK_SET)
        observed = bytearray()
        while len(observed) <= len(payload):
            chunk = os.read(fd, min(1024 * 1024, len(payload) + 1 - len(observed)))
            if not chunk:
                break
            observed.extend(chunk)
        info = os.fstat(fd)
        named = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            bytes(observed) != payload
            or (info.st_dev, info.st_ino) != (row.get("dev"), row.get("ino"))
            or (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino)
            or info.st_nlink != 1
            or info.st_uid != uid
            or info.st_gid != gid
            or stat.S_IMODE(info.st_mode) != mode
        ):
            raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", path)

    @staticmethod
    def _external_retained_path(tag: str, sha256: str, suffix: str) -> Path:
        if not isinstance(tag, str) or not tag or not sha256.startswith("sha256:"):
            raise BrokerExecutorError("MACOS_BACKEND_RETAINED_PATH_INVALID")
        return Path(f"{installer.ROLLBACK_EVIDENCE_PREFIX}-{tag}-{sha256[7:]}.{suffix}")

    @staticmethod
    def _write_external_retained(path: Path, payload: bytes, *, mode: int) -> None:
        parent = Path(installer.STAGING_PARENT)
        if path.parent != parent or not path.name.startswith(
            Path(installer.ROLLBACK_EVIDENCE_PREFIX).name + "-"
        ):
            raise BrokerExecutorError("MACOS_BACKEND_RETAINED_PATH_INVALID")
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = -1
        temp_name = f".{path.name}.w3-retained-tmp"
        try:
            parent_info = os.fstat(parent_fd)
            if (
                parent_info.st_uid != 0
                or parent_info.st_gid != 0
                or stat.S_IMODE(parent_info.st_mode) != 0o700
            ):
                raise BrokerExecutorError("MACOS_BACKEND_RETAINED_PARENT_UNPROTECTED")
            try:
                final_info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                final_info = None
            try:
                temp_info = os.stat(temp_name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                temp_info = None
            if final_info is not None:
                raise BrokerExecutorError("MACOS_BACKEND_RETAINED_TARGET_PREEXISTS", str(path))
            if temp_info is not None:
                if (
                    not stat.S_ISREG(temp_info.st_mode)
                    or temp_info.st_nlink != 1
                    or temp_info.st_uid != 0
                ):
                    raise BrokerExecutorError("MACOS_BACKEND_RETAINED_TEMP_INVALID", str(path))
                temp_fd = os.open(temp_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
                try:
                    existing = bytearray()
                    while True:
                        chunk = os.read(temp_fd, 1024 * 1024)
                        if not chunk:
                            break
                        existing.extend(chunk)
                        if len(existing) > len(payload):
                            break
                finally:
                    os.close(temp_fd)
                if bytes(existing) != payload:
                    os.unlink(temp_name, dir_fd=parent_fd)
                    os.fsync(parent_fd)
                    temp_info = None
                else:
                    os.link(
                        temp_name,
                        path.name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    os.unlink(temp_name, dir_fd=parent_fd)
                    os.fsync(parent_fd)
                    return
            fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                mode,
                dir_fd=parent_fd,
            )
            os.fchown(fd, 0, 0)
            os.fchmod(fd, mode)
            offset = 0
            while offset < len(payload):
                count = os.write(fd, payload[offset:])
                if count <= 0:
                    raise BrokerExecutorError("MACOS_BACKEND_ZERO_WRITE", str(path))
                offset += count
            os.fsync(fd)
            os.link(
                temp_name,
                path.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            os.unlink(temp_name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            with suppress(FileNotFoundError):
                os.unlink(temp_name, dir_fd=parent_fd)
            os.close(parent_fd)

    def _verify_external_retained(self, path: Path, payload: bytes, *, mode: int) -> None:
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            final = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            temp_name = f".{path.name}.w3-retained-tmp"
            try:
                temp = os.stat(temp_name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                temp = None
            if temp is not None:
                if (
                    final.st_nlink != 2
                    or temp.st_nlink != 2
                    or (final.st_dev, final.st_ino) != (temp.st_dev, temp.st_ino)
                ):
                    raise BrokerExecutorError("MACOS_BACKEND_RETAINED_TEMP_INVALID", str(path))
                os.unlink(temp_name, dir_fd=parent_fd)
                os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        actual = secure_read(path, FilePolicy(0, 0, mode), max_bytes=len(payload) + 1)
        if actual != payload:
            raise BrokerExecutorError("MACOS_BACKEND_RETAINED_POSTIMAGE_MISMATCH", str(path))

    def _archive_and_remove_owned_file(
        self,
        row: Mapping[str, object],
        *,
        tag: str,
        missing_archive: Path | None = None,
    ) -> Path:
        path = str(row.get("path"))
        sha256 = row.get("sha256")
        size = row.get("size")
        if row.get("kind") != "file" or not isinstance(sha256, str) or type(size) is not int:
            raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_RECEIPT_INVALID", path)
        target = self._external_retained_path(tag, sha256, "json")
        target_exists = not self._absent(str(target))
        source_exists = not self._absent(path)
        if source_exists:
            parent_fd, fd, payload = self._open_receipt_owned_file(row, path)
            try:
                if target_exists:
                    self._verify_external_retained(target, payload, mode=0o444)
                else:
                    self._write_external_retained(target, payload, mode=0o444)
                self._recheck_held_owned_file(
                    row,
                    path,
                    parent_fd,
                    fd,
                    payload,
                    uid=int(row["uid"]),
                    gid=int(row["gid"]),
                    mode=stat.S_IMODE(int(row["mode"])),
                )
                os.unlink(Path(path).name, dir_fd=parent_fd)
                os.fsync(parent_fd)
                try:
                    os.stat(Path(path).name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", path)
                return target
            finally:
                os.close(fd)
                os.close(parent_fd)
        if target_exists:
            raw = secure_read(target, FilePolicy(0, 0, 0o444), max_bytes=int(size) + 1)
            if len(raw) != size or "sha256:" + hashlib.sha256(raw).hexdigest() != sha256:
                raise BrokerExecutorError("MACOS_BACKEND_RETAINED_POSTIMAGE_MISMATCH", str(target))
            return target
        if missing_archive is not None and not self._absent(str(missing_archive)):
            raw = secure_read(missing_archive, FilePolicy(0, 0, 0o444), max_bytes=int(size) + 1)
            if len(raw) == size and "sha256:" + hashlib.sha256(raw).hexdigest() == sha256:
                return missing_archive
        raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISSING", path)

    def _quarantine_seed(self, row: Mapping[str, object]) -> None:
        source = str(row.get("path"))
        sha256 = row.get("sha256")
        size = row.get("size")
        if source != installer.SIGNING_KEY_PATH or not isinstance(sha256, str) or size != 32:
            raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_RECEIPT_INVALID", source)
        target = self._external_retained_path("private-key", sha256, "seed")
        source_exists = not self._absent(source)
        target_exists = not self._absent(str(target))
        payload: bytes | None = None
        if source_exists:
            parent_fd, fd, payload = self._open_receipt_owned_file(
                row,
                source,
                allow_quarantined_metadata=True,
            )
            try:
                info = os.fstat(fd)
                os.fchown(fd, 0, 0)
                os.fchmod(fd, 0o400)
                os.fsync(fd)
                if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != (info.st_dev, info.st_ino):
                    raise BrokerExecutorError("MACOS_BACKEND_KEY_QUARANTINE_INVALID")
                if "sha256:" + hashlib.sha256(payload).hexdigest() != sha256:
                    raise BrokerExecutorError("MACOS_BACKEND_KEY_QUARANTINE_INVALID")
                if target_exists:
                    self._verify_external_retained(target, payload, mode=0o400)
                else:
                    self._write_external_retained(target, payload, mode=0o400)
                self._recheck_held_owned_file(
                    row,
                    source,
                    parent_fd,
                    fd,
                    payload,
                    uid=0,
                    gid=0,
                    mode=0o400,
                )
                os.unlink(Path(source).name, dir_fd=parent_fd)
                os.fsync(parent_fd)
                try:
                    os.stat(Path(source).name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise BrokerExecutorError("MACOS_BACKEND_KEY_QUARANTINE_INVALID")
                return
            finally:
                os.close(fd)
                os.close(parent_fd)
        if not target_exists:
            raise BrokerExecutorError("MACOS_BACKEND_KEY_QUARANTINE_MISSING")
        raw = secure_read(target, FilePolicy(0, 0, 0o400), max_bytes=33)
        if len(raw) != 32 or "sha256:" + hashlib.sha256(raw).hexdigest() != sha256:
            raise BrokerExecutorError("MACOS_BACKEND_KEY_QUARANTINE_INVALID")

    def rollback(self, rollback_id: str, details: Mapping[str, object]) -> int:
        receipts = details.get("ownership_receipts")
        owned = details.get("owned_sources")
        if not isinstance(receipts, Mapping) or not isinstance(owned, list) or not owned:
            raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_OWNERSHIP_REQUIRED", rollback_id)
        receipt_rows: dict[str, tuple[dict[str, object], ...]] = {}
        for source in owned:
            receipt = receipts.get(source)
            if not isinstance(source, str) or not isinstance(receipt, Mapping):
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_RECEIPT_INVALID", rollback_id)
            receipt_rows[source] = self._validate_ownership_receipt(source, receipt)
        if rollback_id == "withdraw-authority":
            rows = [
                row
                for rows in receipt_rows.values()
                for row in rows
                if row.get("path") == installer.AUTHORITY_REGISTRY_PATH
            ]
            if len(rows) != 1:
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_RECEIPT_INVALID", rollback_id)
            self._archive_and_remove_owned_file(rows[0], tag="authority")
        elif rollback_id.startswith("stop-"):
            label, plist = {
                "stop-broker": (
                    installer.BROKER_PLIST_LABEL,
                    installer.EXPECTED_ARTIFACT_PATHS["broker-plist"],
                ),
                "stop-anchor": (
                    installer.ANCHOR_PLIST_LABEL,
                    installer.EXPECTED_ARTIFACT_PATHS["anchor-plist"],
                ),
                "stop-launcher": (
                    installer.LAUNCHER_PLIST_LABEL,
                    installer.EXPECTED_ARTIFACT_PATHS["launcher-plist"],
                ),
            }[rollback_id]
            registrations = [
                row
                for rows in receipt_rows.values()
                for row in rows
                if row.get("kind") == "launchd-registration" and row.get("label") == label
            ]
            if len(registrations) != 1:
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_RECEIPT_INVALID", rollback_id)
            if self._launchd_registered(label):
                if self._launchd_job_receipt(label, plist) != registrations[0]:
                    raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", label)
                self._run(("/bin/launchctl", "bootout", f"system/{label}"))
            if self._launchd_registered(label):
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", label)
        elif rollback_id == "archive-durable-evidence":
            payload = protocol.canonical_bytes(dict(receipts))
            digest = "sha256:" + hashlib.sha256(payload).hexdigest()
            archive = self._external_retained_path("ownership-receipts", digest, "json")
            if self._absent(str(archive)):
                self._write_external_retained(archive, payload, mode=0o600)
            else:
                self._verify_external_retained(archive, payload, mode=0o600)
        elif rollback_id == "quarantine-signing-key":
            rows = [row for rows in receipt_rows.values() for row in rows]
            by_path = {
                str(row.get("path")): row for row in rows if isinstance(row.get("path"), str)
            }
            seed_row = by_path.get(installer.SIGNING_KEY_PATH)
            if seed_row is not None:
                self._quarantine_seed(seed_row)
            authority_row = by_path.get(installer.AUTHORITY_CANDIDATE_PATH)
            authority_archive = None
            if authority_row is not None and isinstance(authority_row.get("sha256"), str):
                authority_archive = self._external_retained_path(
                    "authority", str(authority_row["sha256"]), "json"
                )
            for path, tag in (
                (installer.PUBLIC_KEY_REGISTRY_PATH, "public-key-registry"),
                (installer.AUTHORITY_CANDIDATE_PATH, "authority"),
                (installer.ANCHOR_CONFIG_PATH, "anchor-config"),
            ):
                row = by_path.get(path)
                if row is not None:
                    self._archive_and_remove_owned_file(
                        row,
                        tag=tag,
                        missing_archive=authority_archive
                        if path == installer.AUTHORITY_CANDIDATE_PATH
                        else None,
                    )
        elif rollback_id == "remove-mutable-state":
            for path in (installer.PUBLICATION_ACTIVE, installer.RUNS_ACTIVE):
                rows = [
                    row
                    for source_rows in receipt_rows.values()
                    for row in source_rows
                    if row.get("path") == path
                ]
                if not rows:
                    continue
                if self._absent(path):
                    continue
                self._receipt_row_matches_path(rows[-1], path)
                os.rmdir(path)
                self._fsync_parent(Path(path))
        elif rollback_id == "remove-installed-code-children-first":
            rows_by_path: dict[str, Mapping[str, object]] = {}
            allowed_paths = set(self._install_rows) | {installer.INSTALL_BUNDLE_MANIFEST_PATH}
            for rows in receipt_rows.values():
                for row in rows:
                    path = row.get("path")
                    if (
                        row.get("kind") == "file"
                        and isinstance(path, str)
                        and path in allowed_paths
                    ):
                        rows_by_path[path] = row
            if not rows_by_path:
                raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_RECEIPT_INVALID", rollback_id)
            for path, row in sorted(
                rows_by_path.items(), key=lambda item: (item[0].count("/"), item[0]), reverse=True
            ):
                if self._absent(path):
                    continue
                self._receipt_row_matches_path(row, path)
                os.unlink(path)
                self._fsync_parent(Path(path))
        elif rollback_id == "remove-created-identities-last":
            for source in reversed(owned):
                role = {
                    "create-identity-metisbroker": "broker",
                    "create-identity-metisrunner": "runner",
                    "create-identity-metisanchor": "anchor",
                }[source]
                principal = installer.FIXED_PRINCIPALS[role]
                receipt = receipts[source]
                operation_ids = self._partial_operation_ids(receipt)
                full = receipt.get("kind") == "w3-phase-b-install-ownership-receipt"
                if full:
                    self._account_row(role)
                delete_user = full or any(
                    operation.startswith("create-user-record-") for operation in operation_ids
                )
                delete_group = full or any(
                    operation.startswith("create-group-record-") for operation in operation_ids
                )
                rows = receipt_rows[source]
                latest_by_record = {
                    str(row["record"]): row
                    for row in rows
                    if row.get("kind") == "directory-service-record"
                    and isinstance(row.get("record"), str)
                }
                if delete_user:
                    try:
                        pwd.getpwnam(str(principal["name"]))
                    except KeyError:
                        pass
                    else:
                        record = f"/Users/{principal['name']}"
                        expected = latest_by_record.get(record)
                        if expected is not None:
                            raw = self._run(("/usr/bin/dscl", ".", "-read", record))
                            if "sha256:" + hashlib.sha256(raw).hexdigest() != expected.get(
                                "sha256"
                            ):
                                raise BrokerExecutorError(
                                    "MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", record
                                )
                        self._run(("/usr/bin/dscl", ".", "-delete", record))
                        try:
                            pwd.getpwnam(str(principal["name"]))
                        except KeyError:
                            pass
                        else:
                            raise BrokerExecutorError(
                                "MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", record
                            )
                if delete_group:
                    try:
                        grp.getgrnam(str(principal["group"]))
                    except KeyError:
                        pass
                    else:
                        record = f"/Groups/{principal['group']}"
                        expected = latest_by_record.get(record)
                        if expected is not None:
                            raw = self._run(("/usr/bin/dscl", ".", "-read", record))
                            if "sha256:" + hashlib.sha256(raw).hexdigest() != expected.get(
                                "sha256"
                            ):
                                raise BrokerExecutorError(
                                    "MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", record
                                )
                        self._run(("/usr/bin/dscl", ".", "-delete", record))
                        try:
                            grp.getgrnam(str(principal["group"]))
                        except KeyError:
                            pass
                        else:
                            raise BrokerExecutorError(
                                "MACOS_BACKEND_ROLLBACK_POSTIMAGE_MISMATCH", record
                            )
        else:
            raise BrokerExecutorError("MACOS_BACKEND_ROLLBACK_UNIMPLEMENTED", rollback_id)
        return 1


_ROLLBACK_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("withdraw-authority", ("register-authority",)),
    ("stop-broker", ("bootstrap-broker",)),
    ("stop-anchor", ("bootstrap-anchor",)),
    ("stop-launcher", ("bootstrap-launcher",)),
    ("archive-durable-evidence", ("precreate-durable-leaves", "provision-signing-key")),
    ("quarantine-signing-key", ("provision-signing-key",)),
    ("remove-mutable-state", ("precreate-durable-leaves",)),
    (
        "remove-installed-code-children-first",
        (
            "install-broker-code",
            "install-runtime",
            "install-release",
            "install-launcher",
            "install-launchd-plists",
        ),
    ),
    (
        "remove-created-identities-last",
        (
            "create-identity-metisbroker",
            "create-identity-metisrunner",
            "create-identity-metisanchor",
        ),
    ),
)


def _validate_install_plan(plan: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    try:
        expected = installer.validate_install_plan(plan)
    except installer.InstallerError as error:
        raise BrokerExecutorError("INSTALL_PLAN_INVALID", str(error)) from error
    return tuple(dict(row) for row in expected["steps"])


def _transition(
    journal: TransitionJournal,
    *,
    transaction_id: int,
    event: str,
    plan_sha256: str,
    bundle_sha256: str,
    bundle_file_sha256: str | None = None,
    step_id: str | None,
    operation_id: str | None = None,
    operation_intent: Mapping[str, object] | None = None,
    ownership_receipt: Mapping[str, object] | None = None,
) -> None:
    journal.append(
        {
            "schema_version": 1,
            "kind": INSTALL_JOURNAL_KIND,
            "transaction_id": transaction_id,
            "event": event,
            "plan_sha256": plan_sha256,
            "bundle_sha256": bundle_sha256,
            "bundle_file_sha256": bundle_sha256
            if bundle_file_sha256 is None
            else bundle_file_sha256,
            "step_id": step_id,
            "operation_id": operation_id,
            "operation_intent": None if operation_intent is None else dict(operation_intent),
            "ownership_receipt": None if ownership_receipt is None else dict(ownership_receipt),
        }
    )


def _payloads(records: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for record in records:
        payload = record.get("payload")
        fields = {
            "transaction_id",
            "event",
            "plan_sha256",
            "bundle_sha256",
            "bundle_file_sha256",
            "step_id",
            "operation_id",
            "operation_intent",
            "ownership_receipt",
        }
        if not isinstance(payload, dict) or set(payload) != fields:
            raise BrokerExecutorError("INSTALL_JOURNAL_CORRUPT", "transition payload")
        if type(payload["transaction_id"]) is not int or int(payload["transaction_id"]) < 1:
            raise BrokerExecutorError("INSTALL_JOURNAL_CORRUPT", "transaction id")
        if payload["ownership_receipt"] is not None and not isinstance(
            payload["ownership_receipt"], dict
        ):
            raise BrokerExecutorError("INSTALL_JOURNAL_CORRUPT", "ownership receipt")
        if payload["operation_intent"] is not None and not isinstance(
            payload["operation_intent"], dict
        ):
            raise BrokerExecutorError("INSTALL_JOURNAL_CORRUPT", "operation intent")
        payloads.append(dict(payload))
    return payloads


def _journal_segments(records: Sequence[Mapping[str, object]]) -> list[list[dict[str, object]]]:
    payloads = _payloads(records)
    segments: list[list[dict[str, object]]] = []
    terminal = {"plan-complete", "recovery-complete"}
    for payload in payloads:
        event = payload["event"]
        transaction_id = int(payload["transaction_id"])
        if event == "transaction-start":
            if payload["step_id"] is not None or transaction_id != len(segments) + 1:
                raise BrokerExecutorError("INSTALL_JOURNAL_SEGMENT_INVALID")
            if segments and segments[-1][-1]["event"] not in terminal:
                raise BrokerExecutorError("INSTALL_JOURNAL_SEGMENT_OVERLAP")
            if segments and segments[-1][-1]["event"] == "plan-complete":
                raise BrokerExecutorError("INSTALL_JOURNAL_AFTER_APPLIED_PLAN")
            segments.append([payload])
            continue
        if not segments or transaction_id != int(segments[-1][0]["transaction_id"]):
            raise BrokerExecutorError("INSTALL_JOURNAL_SEGMENT_INVALID")
        if segments[-1][-1]["event"] in terminal:
            raise BrokerExecutorError("INSTALL_JOURNAL_AFTER_TERMINAL")
        if (
            payload["plan_sha256"] != segments[-1][0]["plan_sha256"]
            or payload["bundle_sha256"] != segments[-1][0]["bundle_sha256"]
            or payload["bundle_file_sha256"] != segments[-1][0]["bundle_file_sha256"]
        ):
            raise BrokerExecutorError("INSTALL_JOURNAL_SEGMENT_BINDING_MISMATCH")
        segments[-1].append(payload)
    for segment in segments:
        _validate_operation_journal_order(segment)
    return segments


def _validate_operation_journal_order(segment: Sequence[Mapping[str, object]]) -> None:
    operation_mode = any(
        row["event"] in {"operation-start", "operation-complete"} for row in segment
    )
    if not operation_mode:
        return
    step_index = -1
    active_step: str | None = None
    operation_index = 0
    active_operation: str | None = None
    seen_operation_units: set[str] = set()
    rollback_started = False
    for row in segment[1:]:
        event = row["event"]
        if event.startswith("rollback-") or event.startswith("recovery-"):
            rollback_started = True
            active_step = None
            active_operation = None
            continue
        if rollback_started or event == "plan-complete":
            continue
        if event == "step-start":
            step_index += 1
            if (
                step_index >= len(installer.INSTALL_STEP_IDS)
                or row["step_id"] != installer.INSTALL_STEP_IDS[step_index]
                or active_step is not None
            ):
                raise BrokerExecutorError("INSTALL_JOURNAL_OPERATION_ORDER_INVALID")
            active_step = str(row["step_id"])
            operation_index = 0
            seen_operation_units = set()
            continue
        if event == "operation-start":
            operations = installer.MACOS_BACKEND_OPERATION_ROSTER.get(str(active_step), ())
            operation_id = str(row["operation_id"])
            base = operation_id.split("::", 1)[0]
            if (
                operation_index < len(operations)
                and base != operations[operation_index]
                and operation_index + 1 < len(operations)
                and base == operations[operation_index + 1]
            ):
                operation_index += 1
            if (
                active_step is None
                or active_operation is not None
                or operation_index >= len(operations)
                or base != operations[operation_index]
                or row["step_id"] != active_step
                or operation_id in seen_operation_units
            ):
                raise BrokerExecutorError("INSTALL_JOURNAL_OPERATION_ORDER_INVALID")
            active_operation = operation_id
            seen_operation_units.add(operation_id)
            continue
        if event == "operation-complete":
            if (
                active_step is None
                or row["step_id"] != active_step
                or row["operation_id"] != active_operation
            ):
                raise BrokerExecutorError("INSTALL_JOURNAL_OPERATION_ORDER_INVALID")
            active_operation = None
            continue
        if event == "step-complete":
            operations = installer.MACOS_BACKEND_OPERATION_ROSTER.get(str(active_step), ())
            if (
                active_step is None
                or active_operation is not None
                or operation_index != len(operations) - 1
                or row["step_id"] != active_step
            ):
                raise BrokerExecutorError("INSTALL_JOURNAL_OPERATION_ORDER_INVALID")
            active_step = None
            continue
        raise BrokerExecutorError("INSTALL_JOURNAL_OPERATION_EVENT_INVALID", str(event))


def _partial_operation_receipt(
    step_id: str,
    operations: Sequence[tuple[str, Mapping[str, object]]],
) -> dict[str, object]:
    rows = [
        {"operation_id": operation_id, "ownership_receipt": dict(receipt)}
        for operation_id, receipt in operations
    ]
    if not rows or len({row["operation_id"] for row in rows}) != len(rows):
        raise BrokerExecutorError("INSTALL_PARTIAL_OWNERSHIP_RECEIPT_INVALID", step_id)
    return {
        "schema_version": 1,
        "kind": "w3-phase-b-install-partial-ownership-receipt",
        "step_id": step_id,
        "operations": rows,
        "operations_sha256": "sha256:" + hashlib.sha256(protocol.canonical_bytes(rows)).hexdigest(),
    }


def _recover_operation_ownership(
    payloads: Sequence[Mapping[str, object]],
    *,
    backend: MacOSInstallBackend,
    journal: TransitionJournal,
    transaction_id: int,
    plan_sha256: str,
    bundle_sha256: str,
    bundle_file_sha256: str,
) -> tuple[set[str], set[str], dict[str, Mapping[str, object]]]:
    """Reconcile the one possible in-flight unit and rebuild durable ownership."""

    starts: list[Mapping[str, object]] = []
    completed_operations: dict[tuple[str, str], Mapping[str, object] | None] = {}
    step_receipts: dict[str, Mapping[str, object]] = {}
    completed_steps: set[str] = set()
    for row in payloads:
        event = row["event"]
        if event == "operation-start":
            starts.append(row)
        elif event == "operation-complete":
            key = (str(row["step_id"]), str(row["operation_id"]))
            if key in completed_operations:
                raise BrokerExecutorError("INSTALL_JOURNAL_OPERATION_DUPLICATE_COMPLETION")
            receipt = row["ownership_receipt"]
            completed_operations[key] = None if receipt is None else dict(receipt)
        elif event == "step-complete" and row["step_id"] is not None:
            step_id = str(row["step_id"])
            completed_steps.add(step_id)
            if isinstance(row["ownership_receipt"], Mapping):
                step_receipts[step_id] = dict(row["ownership_receipt"])

    unmatched = [
        row
        for row in starts
        if (str(row["step_id"]), str(row["operation_id"])) not in completed_operations
    ]
    if len(unmatched) > 1:
        raise BrokerExecutorError("INSTALL_JOURNAL_MULTIPLE_INFLIGHT_OPERATIONS")
    if unmatched:
        row = unmatched[0]
        step_id = str(row["step_id"])
        operation_id = str(row["operation_id"])
        intent = row["operation_intent"]
        reconciled = backend.reconcile_operation(
            step_id,
            operation_id,
            dict(intent) if isinstance(intent, Mapping) else None,
        )
        receipt = reconciled.ownership_receipt
        _transition(
            journal,
            transaction_id=transaction_id,
            event="operation-complete",
            plan_sha256=plan_sha256,
            bundle_sha256=bundle_sha256,
            bundle_file_sha256=bundle_file_sha256,
            step_id=step_id,
            operation_id=operation_id,
            ownership_receipt=receipt,
        )
        completed_operations[(step_id, operation_id)] = None if receipt is None else dict(receipt)

    operation_receipts: dict[str, list[tuple[str, Mapping[str, object]]]] = {}
    for row in starts:
        key = (str(row["step_id"]), str(row["operation_id"]))
        receipt = completed_operations.get(key)
        if isinstance(receipt, Mapping):
            operation_receipts.setdefault(key[0], []).append((key[1], receipt))
    for step_id, rows in operation_receipts.items():
        if step_id not in step_receipts:
            step_receipts[step_id] = _partial_operation_receipt(step_id, rows)
    possibly_effected = set(step_receipts)
    return possibly_effected, completed_steps, step_receipts


def _rollback_attempts(
    *,
    possibly_effected: set[str],
    completed: set[str],
    ownership_receipts: Mapping[str, Mapping[str, object]],
    already_rolled_back: set[str],
    backend: InstallerBackend,
    journal: TransitionJournal,
    transaction_id: int,
    plan_sha256: str,
    bundle_sha256: str,
    bundle_file_sha256: str | None = None,
) -> list[str]:
    failures: list[str] = []
    # Every rollback action mutates host state (including bootout and authority
    # withdrawal).  A mere START is never ownership evidence.
    destructive = {rollback_id for rollback_id, _sources in _ROLLBACK_SOURCES}
    for rollback_id, sources in _ROLLBACK_SOURCES:
        if rollback_id in already_rolled_back or not possibly_effected.intersection(sources):
            continue
        affected = set(sources).intersection(possibly_effected)
        owned = affected.intersection(ownership_receipts)
        ambiguous = affected - owned
        if rollback_id in destructive and ambiguous:
            _transition(
                journal,
                transaction_id=transaction_id,
                event="rollback-retained-ambiguous",
                plan_sha256=plan_sha256,
                bundle_sha256=bundle_sha256,
                bundle_file_sha256=bundle_file_sha256,
                step_id=rollback_id,
            )
            failures.append(
                f"{rollback_id}:ambiguous-no-ownership-receipt:{','.join(sorted(ambiguous))}"
            )
            continue
        details = {
            "completed_sources": [source for source in sources if source in completed],
            "possibly_effected_sources": [source for source in sources if source in affected],
            "owned_sources": [source for source in sources if source in owned],
            "ownership_receipts": {
                source: dict(ownership_receipts[source]) for source in sources if source in owned
            },
            "children_first": rollback_id
            in {"remove-mutable-state", "remove-installed-code-children-first"},
            "retained": list(installer.RETAINED_ON_ROLLBACK),
        }
        try:
            _transition(
                journal,
                transaction_id=transaction_id,
                event="rollback-start",
                plan_sha256=plan_sha256,
                bundle_sha256=bundle_sha256,
                bundle_file_sha256=bundle_file_sha256,
                step_id=rollback_id,
            )
        except Exception as journal_error:
            failures.append(f"{rollback_id}:journal-start:{type(journal_error).__name__}")
        try:
            count = backend.rollback(rollback_id, details)
            if type(count) is not int or count < 1:
                raise BrokerExecutorError("ROLLBACK_NO_EFFECT", rollback_id)
        except Exception as rollback_error:
            failures.append(f"{rollback_id}:backend:{type(rollback_error).__name__}")
            outcome = "rollback-failed"
        else:
            outcome = "rollback-complete"
        try:
            _transition(
                journal,
                transaction_id=transaction_id,
                event=outcome,
                plan_sha256=plan_sha256,
                bundle_sha256=bundle_sha256,
                bundle_file_sha256=bundle_file_sha256,
                step_id=rollback_id,
            )
        except Exception as journal_error:
            failures.append(f"{rollback_id}:journal-outcome:{type(journal_error).__name__}")
    return failures


def recover_install_plan(
    plan: Mapping[str, object],
    bundle_manifest: Mapping[str, object],
    *,
    backend: InstallerBackend,
    journal: TransitionJournal,
) -> dict[str, object]:
    """Replay a durable journal and finish fail-closed rollback before new apply."""

    _validate_install_plan(plan)
    try:
        bundle = installer.validate_bundle_manifest(bundle_manifest, require_frozen=True)
    except installer.InstallerError as error:
        raise BrokerExecutorError("RECOVERY_FROZEN_BUNDLE_INVALID", str(error)) from error
    with journal.session() as locked_journal:
        return _recover_install_plan_locked(plan, bundle, backend=backend, journal=locked_journal)


def _recover_install_plan_locked(
    plan: Mapping[str, object],
    bundle: Mapping[str, object],
    *,
    backend: InstallerBackend,
    journal: TransitionJournal,
    expected_bundle_file_sha256: str | None = None,
) -> dict[str, object]:
    plan_sha256 = "sha256:" + installer.plan_digest(plan)
    bundle_sha256 = str(bundle["bundle_sha256"])
    records = journal.records(repair_torn_tail=True)
    segments = _journal_segments(records)
    if not segments:
        return {"status": "clean", "rollback_failures": []}
    payloads = segments[-1]
    transaction_id = int(payloads[0]["transaction_id"])
    if (
        payloads[0]["plan_sha256"] != plan_sha256
        or payloads[0]["bundle_sha256"] != bundle_sha256
        or (
            expected_bundle_file_sha256 is not None
            and payloads[0]["bundle_file_sha256"] != expected_bundle_file_sha256
        )
    ):
        raise BrokerExecutorError("RECOVERY_JOURNAL_BINDING_MISMATCH")
    if payloads[-1]["event"] == "plan-complete":
        return {"status": "already-complete", "rollback_failures": []}
    if payloads[-1]["event"] == "recovery-complete":
        return {"status": "rolled-back", "rollback_failures": []}
    if type(backend) is MacOSInstallBackend:
        possibly_effected, completed, ownership_receipts = _recover_operation_ownership(
            payloads,
            backend=backend,
            journal=journal,
            transaction_id=transaction_id,
            plan_sha256=plan_sha256,
            bundle_sha256=bundle_sha256,
            bundle_file_sha256=str(payloads[0]["bundle_file_sha256"]),
        )
    else:
        possibly_effected = {
            str(row["step_id"])
            for row in payloads
            if row["event"] == "step-start" and row["step_id"] is not None
        }
        completed = {
            str(row["step_id"])
            for row in payloads
            if row["event"] == "step-complete" and row["step_id"] is not None
        }
        ownership_receipts = {
            str(row["step_id"]): dict(row["ownership_receipt"])
            for row in payloads
            if row["event"] == "step-complete"
            and row["step_id"] is not None
            and isinstance(row["ownership_receipt"], dict)
        }
    already_rolled_back = {
        str(row["step_id"])
        for row in payloads
        if row["event"] == "rollback-complete" and row["step_id"] is not None
    }
    failures = _rollback_attempts(
        possibly_effected=possibly_effected,
        completed=completed,
        ownership_receipts=ownership_receipts,
        already_rolled_back=already_rolled_back,
        backend=backend,
        journal=journal,
        transaction_id=transaction_id,
        plan_sha256=plan_sha256,
        bundle_sha256=bundle_sha256,
        bundle_file_sha256=str(payloads[0]["bundle_file_sha256"]),
    )
    _transition(
        journal,
        transaction_id=transaction_id,
        event="recovery-complete" if not failures else "recovery-failed",
        plan_sha256=plan_sha256,
        bundle_sha256=bundle_sha256,
        bundle_file_sha256=str(payloads[0]["bundle_file_sha256"]),
        step_id=None,
    )
    if failures:
        raise BrokerExecutorError("INSTALL_RECOVERY_FAILED", ",".join(failures))
    return {"status": "rolled-back", "rollback_failures": []}


def execute_install_plan(
    plan: Mapping[str, object],
    *,
    apply: bool = False,
    supplied_plan_digest: str | None = None,
    euid: int | None = None,
    backend: InstallerBackend | None = None,
    journal: TransitionJournal | None = None,
    bundle_manifest: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return a deterministic dry-run or execute transactionally after all guards."""

    steps = _validate_install_plan(plan)
    digest = installer.plan_digest(plan)
    dry = {
        "status": "dry-run",
        "plan_sha256": f"sha256:{digest}",
        "steps": [row["id"] for row in steps],
        "backend_calls": 0,
    }
    if not apply:
        return dry
    actual_euid = os.geteuid() if euid is None else euid
    if actual_euid != 0:
        raise BrokerExecutorError("APPLY_REQUIRES_ROOT")
    if supplied_plan_digest != digest:
        raise BrokerExecutorError("APPLY_PLAN_DIGEST_MISMATCH")
    if backend is None or journal is None:
        raise BrokerExecutorError("APPLY_BACKEND_AND_JOURNAL_REQUIRED")
    if bundle_manifest is None:
        raise BrokerExecutorError("APPLY_FROZEN_BUNDLE_REQUIRED")
    try:
        frozen_bundle = installer.validate_bundle_manifest(bundle_manifest, require_frozen=True)
    except installer.InstallerError as error:
        raise BrokerExecutorError("APPLY_FROZEN_BUNDLE_INVALID", str(error)) from error
    release_content = str(steps[0]["details"]["release_content_roster_sha256"])
    if frozen_bundle["release_content_roster_sha256"] != f"sha256:{release_content}":
        raise BrokerExecutorError("APPLY_BUNDLE_RELEASE_CONTENT_MISMATCH")
    if frozen_bundle["bundle_sha256"] != steps[0]["details"]["bundle_sha256"]:
        raise BrokerExecutorError("APPLY_PLAN_BUNDLE_MISMATCH")
    if getattr(backend, "operation_roster_sha256", None) != installer.backend_roster_digest():
        raise BrokerExecutorError("APPLY_BACKEND_ROSTER_MISMATCH")
    if type(backend) is MacOSInstallBackend:
        raise BrokerExecutorError("MACOS_BACKEND_INTERNAL_CLI_ONLY")
    with journal.session() as locked_journal:
        return _execute_install_plan_locked(
            plan,
            steps=steps,
            digest=digest,
            frozen_bundle=frozen_bundle,
            backend=backend,
            journal=locked_journal,
            attestation_allowed=False,
        )


def _scrub_bootstrap_runtime_environment(
    environment: MutableMapping[str, str],
    *,
    effective_uid: int,
) -> None:
    """Accept only CPython/Darwin's exact additions, then restore Stage-0's env."""

    expected_path = "/usr/bin:/bin:/usr/sbin:/sbin"
    if set(environment) != {"PATH", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"}:
        raise BrokerExecutorError("BOOTSTRAP_RUNTIME_ENVIRONMENT_INVALID", "keyset")
    if environment.get("PATH") != expected_path or environment.get("LC_CTYPE") != "C.UTF-8":
        raise BrokerExecutorError("BOOTSTRAP_RUNTIME_ENVIRONMENT_INVALID", "locale")
    encoding = environment.get("__CF_USER_TEXT_ENCODING", "")
    match = re.fullmatch(
        r"0x([0-9A-Fa-f]{1,8}):0x[0-9A-Fa-f]{1,8}:0x[0-9A-Fa-f]{1,8}",
        encoding,
    )
    if match is None or int(match.group(1), 16) != effective_uid:
        raise BrokerExecutorError("BOOTSTRAP_RUNTIME_ENVIRONMENT_INVALID", "cf-user")
    environment.pop("LC_CTYPE")
    environment.pop("__CF_USER_TEXT_ENCODING")
    if dict(environment) != {"PATH": expected_path}:
        raise BrokerExecutorError("BOOTSTRAP_RUNTIME_ENVIRONMENT_SCRUB_FAILED")


def _verify_bootstrap_runtime_provenance() -> None:
    """Refuse host effects unless Stage-0 selected the frozen staged runtime."""

    staged_python_root = Path(installer.STAGED_INSTALL_TREE + installer.PYTHON_ROOT)
    expected_executable = Path(
        installer.STAGED_INSTALL_TREE + installer.EXPECTED_ARTIFACT_PATHS["python"]
    )
    expected_executor = Path(
        installer.STAGED_INSTALL_TREE + installer.EXPECTED_ARTIFACT_PATHS["installer-executor"]
    )
    flags = sys.flags
    try:
        _scrub_bootstrap_runtime_environment(os.environ, effective_uid=os.geteuid())
    except BrokerExecutorError as error:
        raise BrokerExecutorError("BOOTSTRAP_RUNTIME_PROVENANCE_REQUIRED") from error
    if (
        Path(sys.executable) != expected_executable
        or Path(__file__) != expected_executor
        or Path.cwd() != Path("/")
        or flags.isolated != 1
        or flags.ignore_environment != 1
        or flags.no_user_site != 1
        or flags.dont_write_bytecode != 1
        or not sys.dont_write_bytecode
    ):
        raise BrokerExecutorError("BOOTSTRAP_RUNTIME_PROVENANCE_REQUIRED")
    root_text = str(staged_python_root) + "/"
    for entry in sys.path:
        if (
            not isinstance(entry, str)
            or not entry
            or not Path(entry).is_absolute()
            or not (entry == str(staged_python_root) or entry.startswith(root_text))
        ):
            raise BrokerExecutorError("BOOTSTRAP_RUNTIME_SYS_PATH_INVALID", str(entry))
    checked: set[str] = set()
    for name, module in tuple(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if origin is None:
            continue
        if (
            not isinstance(origin, str)
            or not Path(origin).is_absolute()
            or not origin.startswith(root_text)
            or origin in checked
        ):
            raise BrokerExecutorError("BOOTSTRAP_RUNTIME_IMPORT_ORIGIN_INVALID", str(name))
        checked.add(origin)
        path = Path(origin)
        MacOSInstallBackend._verify_root_owned_ancestry(path)
        info = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_gid != 0
            or info.st_mode & 0o022
            or info.st_nlink != 1
        ):
            raise BrokerExecutorError("BOOTSTRAP_RUNTIME_IMPORT_ORIGIN_INVALID", str(name))
    if str(expected_executor) not in checked:
        raise BrokerExecutorError("BOOTSTRAP_RUNTIME_EXECUTOR_ORIGIN_MISSING")


def _execute_production_install_plan(
    plan: Mapping[str, object],
    manifest: Mapping[str, object],
    *,
    manifest_raw: bytes,
    supplied_plan_digest: str,
    supplied_bundle_digest: str,
) -> dict[str, object]:
    _verify_bootstrap_runtime_provenance()
    if os.geteuid() != 0:
        raise BrokerExecutorError("APPLY_REQUIRES_ROOT")
    steps = _validate_install_plan(plan)
    plan_digest = installer.plan_digest(plan)
    if supplied_plan_digest != "sha256:" + plan_digest:
        raise BrokerExecutorError("APPLY_PLAN_DIGEST_MISMATCH")
    raw_digest = "sha256:" + hashlib.sha256(manifest_raw).hexdigest()
    if supplied_bundle_digest != raw_digest:
        raise BrokerExecutorError("APPLY_RAW_BUNDLE_DIGEST_MISMATCH")
    try:
        frozen = installer.validate_bundle_manifest(manifest, require_frozen=True)
    except installer.InstallerError as error:
        raise BrokerExecutorError("APPLY_FROZEN_BUNDLE_INVALID", str(error)) from error
    if frozen["bundle_sha256"] != steps[0]["details"]["bundle_sha256"]:
        raise BrokerExecutorError("APPLY_PLAN_BUNDLE_MISMATCH")
    if frozen["release_content_roster_sha256"] != "sha256:" + str(
        steps[0]["details"]["release_content_roster_sha256"]
    ):
        raise BrokerExecutorError("APPLY_BUNDLE_RELEASE_CONTENT_MISMATCH")
    backend = MacOSInstallBackend(frozen)
    if backend.bundle_sha256 != frozen["bundle_sha256"]:
        raise BrokerExecutorError("APPLY_BACKEND_BUNDLE_MISMATCH")
    journal = FileTransitionJournal(
        Path(installer.INSTALL_TRANSITION_JOURNAL_PATH), require_root=True
    )
    with journal.bootstrap_session() as locked_journal:
        return _execute_install_plan_locked(
            plan,
            steps=steps,
            digest=plan_digest,
            frozen_bundle=frozen,
            backend=backend,
            journal=locked_journal,
            attestation_allowed=True,
            bundle_file_sha256=raw_digest,
        )


def _execute_install_plan_locked(
    plan: Mapping[str, object],
    *,
    steps: Sequence[Mapping[str, object]],
    digest: str,
    frozen_bundle: Mapping[str, object],
    backend: InstallerBackend,
    journal: TransitionJournal,
    attestation_allowed: bool,
    bundle_file_sha256: str | None = None,
) -> dict[str, object]:
    existing = journal.records(repair_torn_tail=True)
    segments = _journal_segments(existing)
    if segments and segments[-1][-1]["event"] == "plan-complete":
        latest = segments[-1][0]
        if (
            latest["plan_sha256"] == f"sha256:{digest}"
            and latest["bundle_sha256"] == frozen_bundle["bundle_sha256"]
        ):
            if not attestation_allowed or type(backend) is not MacOSInstallBackend:
                return {
                    "status": "journal-complete-unverified",
                    "plan_sha256": latest["plan_sha256"],
                    "bundle_sha256": latest["bundle_sha256"],
                    "steps": list(installer.INSTALL_STEP_IDS),
                    "backend_calls": 0,
                }
            evidence = backend.verify_final_postconditions()
            return {
                "status": "already-complete",
                "plan_sha256": latest["plan_sha256"],
                "bundle_sha256": latest["bundle_sha256"],
                "steps": list(installer.INSTALL_STEP_IDS),
                "backend_calls": 0,
                "applied_evidence": dict(evidence),
            }
        raise BrokerExecutorError("APPLY_AFTER_COMPLETED_PLAN_FORBIDDEN")
    if segments and segments[-1][-1]["event"] != "recovery-complete":
        recovery = _recover_install_plan_locked(
            plan,
            frozen_bundle,
            backend=backend,
            journal=journal,
            expected_bundle_file_sha256=bundle_file_sha256,
        )
        raise BrokerExecutorError("INSTALL_RECOVERY_REQUIRED", str(recovery["status"]))
    transaction_id = len(segments) + 1
    plan_sha256 = f"sha256:{digest}"
    bundle_sha256 = str(frozen_bundle["bundle_sha256"])
    raw_bundle_sha256 = bundle_sha256 if bundle_file_sha256 is None else bundle_file_sha256
    completed: list[str] = []
    operation_calls = 0
    possibly_effected: list[str] = []
    ownership_receipts: dict[str, Mapping[str, object]] = {}
    _transition(
        journal,
        transaction_id=transaction_id,
        event="transaction-start",
        plan_sha256=plan_sha256,
        bundle_sha256=bundle_sha256,
        bundle_file_sha256=raw_bundle_sha256,
        step_id=None,
    )
    try:
        for step in steps:
            step_id = str(step["id"])
            _transition(
                journal,
                transaction_id=transaction_id,
                event="step-start",
                plan_sha256=plan_sha256,
                bundle_sha256=bundle_sha256,
                bundle_file_sha256=raw_bundle_sha256,
                step_id=step_id,
            )
            possibly_effected.append(step_id)
            if attestation_allowed and type(backend) is MacOSInstallBackend:
                step_operation_count = 0
                for base_operation in installer.MACOS_BACKEND_OPERATION_ROSTER[step_id]:
                    units = backend.operation_units(step_id, base_operation)
                    if not units:
                        raise BrokerExecutorError(
                            "INSTALL_OPERATION_UNIT_ROSTER_EMPTY", base_operation
                        )
                    for operation in units:
                        intent = backend.operation_intent(step_id, operation)
                        _transition(
                            journal,
                            transaction_id=transaction_id,
                            event="operation-start",
                            plan_sha256=plan_sha256,
                            bundle_sha256=bundle_sha256,
                            bundle_file_sha256=raw_bundle_sha256,
                            step_id=step_id,
                            operation_id=operation,
                            operation_intent=intent,
                        )
                        operation_effect = _normalize_backend_effect(
                            backend.apply_operation(step_id, operation), f"{step_id}:{operation}"
                        )
                        if operation_effect.count != 1:
                            raise BrokerExecutorError(
                                "INSTALL_OPERATION_EFFECT_COUNT_MISMATCH", operation
                            )
                        _transition(
                            journal,
                            transaction_id=transaction_id,
                            event="operation-complete",
                            plan_sha256=plan_sha256,
                            bundle_sha256=bundle_sha256,
                            bundle_file_sha256=raw_bundle_sha256,
                            step_id=step_id,
                            operation_id=operation,
                            ownership_receipt=operation_effect.ownership_receipt,
                        )
                        step_operation_count += 1
                        operation_calls += 1
                step_receipt = backend.step_ownership_receipt(step_id)
                effect = BackendEffect(step_operation_count, step_receipt)
            else:
                effect = _normalize_backend_effect(backend.apply(step), step_id)
                expected_effect_count = len(installer.MACOS_BACKEND_OPERATION_ROSTER[step_id])
                if effect.count != expected_effect_count:
                    raise BrokerExecutorError("INSTALL_STEP_EFFECT_COUNT_MISMATCH", step_id)
            if effect.ownership_receipt is not None:
                ownership_receipts[step_id] = dict(effect.ownership_receipt)
            completed.append(step_id)
            _transition(
                journal,
                transaction_id=transaction_id,
                event="step-complete",
                plan_sha256=plan_sha256,
                bundle_sha256=bundle_sha256,
                bundle_file_sha256=raw_bundle_sha256,
                step_id=step_id,
                ownership_receipt=effect.ownership_receipt,
            )
    except Exception as error:
        completed_set = set(completed)
        possibly_effected_set = set(possibly_effected)
        if attestation_allowed and type(backend) is MacOSInstallBackend:
            current_segments = _journal_segments(journal.records(repair_torn_tail=True))
            current_payloads = current_segments[-1]
            possibly_effected_set, completed_set, ownership_receipts = _recover_operation_ownership(
                current_payloads,
                backend=backend,
                journal=journal,
                transaction_id=transaction_id,
                plan_sha256=plan_sha256,
                bundle_sha256=bundle_sha256,
                bundle_file_sha256=raw_bundle_sha256,
            )
        rollback_failures = _rollback_attempts(
            possibly_effected=possibly_effected_set,
            completed=completed_set,
            ownership_receipts=ownership_receipts,
            already_rolled_back=set(),
            backend=backend,
            journal=journal,
            transaction_id=transaction_id,
            plan_sha256=plan_sha256,
            bundle_sha256=bundle_sha256,
            bundle_file_sha256=raw_bundle_sha256,
        )
        terminal = "recovery-failed" if rollback_failures else "recovery-complete"
        try:
            _transition(
                journal,
                transaction_id=transaction_id,
                event=terminal,
                plan_sha256=plan_sha256,
                bundle_sha256=bundle_sha256,
                bundle_file_sha256=raw_bundle_sha256,
                step_id=None,
            )
        except Exception as journal_error:
            rollback_failures.append(f"transaction-terminal:journal:{type(journal_error).__name__}")
        detail = type(error).__name__
        if rollback_failures:
            detail += ";rollback=" + ",".join(rollback_failures)
        raise BrokerExecutorError("INSTALL_TRANSACTION_FAILED", detail) from error
    _transition(
        journal,
        transaction_id=transaction_id,
        event="plan-complete",
        plan_sha256=plan_sha256,
        bundle_sha256=bundle_sha256,
        bundle_file_sha256=raw_bundle_sha256,
        step_id=None,
    )
    result = {
        "status": "simulated-apply",
        "plan_sha256": plan_sha256,
        "bundle_sha256": bundle_sha256,
        "steps": completed,
        "backend_calls": operation_calls
        if attestation_allowed
        else sum(len(installer.MACOS_BACKEND_OPERATION_ROSTER[step]) for step in completed),
    }
    if attestation_allowed and type(backend) is MacOSInstallBackend:
        evidence = backend.applied_evidence
        required = {"authority_sha256", "release_ancestry_sha256", "release_content_roster_sha256"}
        if (
            not isinstance(evidence, Mapping)
            or set(evidence) != required
            or evidence["release_content_roster_sha256"]
            != frozen_bundle["release_content_roster_sha256"]
            or any(not _is_sha256_digest(evidence[field]) for field in required)
        ):
            raise BrokerExecutorError("MACOS_BACKEND_FINAL_ATTESTATION_INVALID")
        result["status"] = "applied"
        result["applied_evidence"] = dict(evidence)
    return result


def parse_executor_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="w3-broker-executor", allow_abbrev=False)
    parser.add_argument(
        "--apply", action="store_true", help="perform the fixed plan instead of printing a dry-run"
    )
    parser.add_argument("--plan-digest", metavar="sha256:HEX")
    parser.add_argument("--bundle-digest", metavar="sha256:HEX")
    namespace = parser.parse_args(list(argv))
    if namespace.apply:
        if not _is_sha256_digest(namespace.plan_digest) or not _is_sha256_digest(
            namespace.bundle_digest
        ):
            raise BrokerExecutorError("CLI_APPLY_EXACT_PLAN_AND_BUNDLE_DIGESTS_REQUIRED")
    elif namespace.plan_digest is not None or namespace.bundle_digest is not None:
        raise BrokerExecutorError("CLI_DIGEST_WITHOUT_APPLY_FORBIDDEN")
    return namespace


def _fixed_canonical_json_payload(
    path: Path, policy: FilePolicy, *, max_bytes: int
) -> tuple[dict[str, object], bytes]:
    raw = secure_read(path, policy, max_bytes=max_bytes)

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BrokerExecutorError("CLI_FIXED_JSON_DUPLICATE_KEY", str(key))
            result[key] = value
        return result

    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise BrokerExecutorError("CLI_FIXED_JSON_INVALID", str(path)) from error
    if (
        not isinstance(document, dict)
        or json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
        != raw
    ):
        raise BrokerExecutorError("CLI_FIXED_JSON_NOT_CANONICAL", str(path))
    return document, raw


def _fixed_canonical_json(path: Path, policy: FilePolicy, *, max_bytes: int) -> dict[str, object]:
    return _fixed_canonical_json_payload(path, policy, max_bytes=max_bytes)[0]


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_executor_args(sys.argv[1:] if argv is None else argv)
    plan = _fixed_canonical_json(
        STAGED_PLAN_PATH, FilePolicy(0, 0, 0o444), max_bytes=protocol.MAX_PAYLOAD_BYTES
    )
    if not arguments.apply:
        result = execute_install_plan(plan, apply=False)
    else:
        manifest, manifest_raw = _fixed_canonical_json_payload(
            STAGED_MANIFEST_PATH, FilePolicy(0, 0, 0o444), max_bytes=INSTALL_BUNDLE_MAX_BYTES
        )
        result = _execute_production_install_plan(
            plan,
            manifest,
            manifest_raw=manifest_raw,
            supplied_plan_digest=str(arguments.plan_digest),
            supplied_bundle_digest=str(arguments.bundle_digest),
        )
    sys.stdout.buffer.write(protocol.canonical_bytes(result) + b"\n")
    return 0


__all__ = [
    "BackendEffect",
    "BrokerExecutorError",
    "CONFIG_KIND",
    "FilePolicy",
    "FileTransitionJournal",
    "InstallerBackend",
    "MacOSInstallBackend",
    "StructuredArgvBackend",
    "build_installed_broker",
    "execute_install_plan",
    "main",
    "parse_executor_args",
    "recover_install_plan",
    "secure_read",
]


if __name__ == "__main__":
    raise SystemExit(main())
