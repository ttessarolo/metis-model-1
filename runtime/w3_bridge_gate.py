#!/usr/bin/env python3
"""Standalone two-fresh-process replay gate for W3 production capsule v3."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 3
REPLAY_ID = "w3-f1-f3-production-capsule-replay-v3"
QUALIFICATION_ID = "w3-f1-f3-production-capsule-qualification-v3"
AUTHORITY_ID = "w3-f1-f3-production-capsule-authority-v3"
CLAIM = "three_ratified_smoke_specs_two_process_replay_only_no_accuracy_claim"
NON_CLAIMS = [
    "executed_preimage_authority=false",
    "no_w1_15_of_15_claim",
    "no_f4_f5_f6_claim",
    "no_benchmark_v1_claim",
    "no_w5_claim",
    "no_semantic_accuracy_claim",
]
NATIVE_EVIDENCE = {
    "path": "manifests/w3-native-loader-evidence.json",
    "manifest_sha256": "sha256:a84ec4511009102f1c2cc23604a4147606e34030809537d1528fd49032f331f6",
}
EXECUTED_PREIMAGE_AUTHORITY = False
REGISTERED_PROTECTED_EXECUTION_BROKER_SHA256: str | None = None
KIMI_REPORT_SHA256 = "sha256:a810598d9b62143f6172a4faa58f91879d4ac19f097cc19255a6ce43356fb83a"
PROJECT_REVISION = "5a5d817bb3df817fbd5d47b7bc4edd4517f8d9b7"
PINNED_METIS_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
PINNED_METIS_TREE = "75473e26deff4084a0eb077a4c3e27d52dc07998"
PINNED_NODE_VERSION = "v22.22.3"
PINNED_NODE_SHA256 = "sha256:5d9d3872911e2340a43b707962e68143de8a4e8d54628845c0c4f2de1fb7cd5c"
PINNED_NODE_BYTES = 112_915_776
PINNED_RUNNER_SHA256 = "sha256:772baa27e981f611681330bc463aef2ebe06b5f4a83ef2a0313ccf66b6dfef5d"
PINNED_LOADER_SHA256 = "sha256:45e3557ce7ee345e2bca7de603c2ef8bc21aa2adb3f305d3f1cf6ee445273fee"
PINNED_LOADER_FLAGS = ["--disable-warning=ExperimentalWarning", "--experimental-loader"]
PINNED_TOOLING = {
    "package_sha256": "sha256:f8130a67f948720b339695fae614f32185610f762d69b85ff600f08971f2fb80",
    "lock_sha256": "sha256:fed109b62f300ed824201f4b167d700072008b0b4a817cbb512a2eee32edc9fb",
    "node_modules_sha256": (
        "sha256:1cea5f2f0371d3c57b9ef9787707bc1079f88dc697c7be2c6c247e4018f6e463"
    ),
}
PINNED_ORACLE_POLICY_SHA256 = (
    "sha256:deb8f45c9dfc2f336dbfb6f69a13e599a51929864ede8229969fa7f6e03f40aa"
)
PINNED_LAUNCHER_POLICY_SHA256 = (
    "sha256:d4f6cb3c41f297d37bf2ba0bf56c271fbfb86da3b15cfe3c05963a5194fa9c97"
)
PINNED_CAPSULE_EXECUTION_POLICY = {
    "sandbox_policy_sha256": (
        "sha256:4f29bf5e092d83993f19ad3d257cafd968a69b708679cecf5edc03cdf018de51"
    ),
    "capsule_ancestor_slots": 32,
    "runtime_ancestor_slots": 32,
    "process_fork": "denied",
    "supervision": "node-session-group-leader",
    "loader_flags": PINNED_LOADER_FLAGS,
}
# Frozen after the qualifier's final formatter pass.  The bridge never imports
# the file being authenticated and cannot accept a caller-selected root.
PINNED_QUALIFIER_SHA256 = "sha256:566c19132ff4d4f0dc7dd974e0d8818c22f6aa5c32ce3ee173104a9cad1c1df2"
QUALIFIER_BOOTSTRAP = """import hashlib
import sys

maximum = 1048576
source = sys.stdin.buffer.read(maximum + 1)
if len(source) > maximum:
    raise SystemExit(120)
qualifier_path = sys.argv.pop(1)
bridge_control_fd = int(sys.argv.pop(1))
bridge_control_nonce = sys.argv.pop(1)
digest = hashlib.sha256(source).hexdigest()
logical_identity = f"qualifier-v3://sha256/{digest}"
sys.argv[0] = logical_identity
namespace = {
    "__name__": "__main__",
    "__file__": logical_identity,
    "__package__": None,
    "__qualifier_preimage__": source,
    "__qualifier_path__": qualifier_path,
    "__bridge_control_fd__": bridge_control_fd,
    "__bridge_control_nonce__": bridge_control_nonce,
}
exec(compile(source, logical_identity, "exec"), namespace, namespace)
"""
QUALIFIER_BOOTSTRAP_SHA256 = (
    "sha256:" + hashlib.sha256(QUALIFIER_BOOTSTRAP.encode("utf-8")).hexdigest()
)
CANDIDATE_MANIFEST_SHA256 = (
    "sha256:4ee3e735179194b838ec38b0c11f1f9a166d640fcfece1eee68b6f9b6dd63bc5"
)
SEMANTIC_REGISTRY_SHA256 = "sha256:9b9aa14836eb6924e61df0ab1e0a7b7224f9958b78056ae66fd27f59868cc7c3"
DEPENDENCY_ROSTER_SHA256 = "db649bc14ee947ff43a2e5dbd540585123a259bb771a087692b72a4c0d463f42"
DEPENDENCY_PYTHON = {
    "implementation": "CPython",
    "version": "3.13.3",
    "abi": "cp313-macosx_arm64",
    "machine": "arm64",
}
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ROLES = {"author": 2, "before": 2, "after": 2, "mutated": 2, "fixed": 2}
ONE_RUN_ROLES = {"author": 1, "before": 1, "after": 1, "mutated": 1, "fixed": 1}
ROLE_FAMILIES = {
    ("F-1", "author"),
    ("F-2", "before"),
    ("F-2", "after"),
    ("F-3", "mutated"),
    ("F-3", "fixed"),
}
LAUNCHER_KEYS = {
    "qualifier_path",
    "qualifier_sha256",
    "python_executable",
    "python_executable_sha256",
    "python_version",
    "required_flags",
    "sandbox_exec_path",
    "sandbox_exec_sha256",
    "sandbox_policy_template_sha256",
    "qualifier_bootstrap_sha256",
}
MAX_REPORT_BYTES = 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_PUBLISHED_BYTES = (5 * MAX_ARTIFACT_BYTES) + MAX_REPORT_BYTES
MAX_EXECUTABLE_BYTES = 128 * 1024 * 1024
GC_POLICY = "separately_ratified_quiescent_exclusive_v1"
ZERO_HASH = "sha256:" + ("0" * 64)
NONCE_MODEL = "excluded_execution_metadata_and_retained_root_physical_identity_only"
REPLAY_HOLDER_CAPS = (16384, 16384, 3 * 1024 * 1024 * 1024, 256 * 1024 * 1024)
RETAINED_ROOT_CAPS = {
    "production-process-root": (512, 512, 128 * 1024 * 1024),
    "production-runtime-root": (8, 8, 128 * 1024 * 1024),
    "production-trusted-root": (4096, 4096, 1024 * 1024 * 1024),
    "qualification-publication-partial-root": (128, 128, 32 * 1024 * 1024),
    "replay-holder-root": REPLAY_HOLDER_CAPS[:3],
}
RETAINED_ROOT_FILE_CAPS = {
    "production-process-root": 8 * 1024 * 1024,
    "production-runtime-root": 128 * 1024 * 1024,
    "production-trusted-root": 8 * 1024 * 1024,
    "qualification-publication-partial-root": 4 * 1024 * 1024,
    "replay-holder-root": REPLAY_HOLDER_CAPS[3],
}
BLOCKED_CHILD_RETAINED_PREFIXES = (
    (),
    ("production-process-root",),
    ("production-process-root", "production-runtime-root"),
    ("production-process-root", "production-runtime-root", "production-trusted-root"),
    (
        "production-process-root",
        "production-runtime-root",
        "production-trusted-root",
        "qualification-publication-partial-root",
    ),
)
BLOCKED_REPLAY_RETAINED_PREFIXES = ((), ("replay-holder-root",))
QUALIFIED_CHILD_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "qualification_id",
        "qualification_kind",
        "status",
        "claim",
        "authority_manifest_sha256",
        "ratification_evidence_sha256",
        "project_revision",
        "source_bundle_manifest_sha256",
        "dependency_bundle_manifest_sha256",
        "dependency_roster_sha256",
        "capsule_manifest_sha256",
        "candidate_manifest_sha256",
        "semantic_registry_sha256",
        "worker_input_sha256",
        "worker_output_sha256",
        "launcher",
        "counts",
        "roles",
        "executions",
        "native_evidence",
        "non_claims",
        "cleanup",
        "manifest_sha256",
    }
)
QUALIFIED_REPLAY_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "replay_id",
        "status",
        "claim",
        "authority_manifest_sha256",
        "runs",
        "normalized_projection_sha256",
        "capsule_manifest_sha256",
        "counts",
        "roles",
        "nonce_model",
        "artifacts",
        "native_evidence",
        "non_claims",
        "cleanup",
        "manifest_sha256",
    }
)
BLOCKED_REPLAY_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "replay_id",
        "status",
        "claim",
        "reason",
        "observed_runs",
        "native_evidence",
        "cleanup",
    }
)
BRIDGE_CHILD_ROLES = frozenset(
    {
        "node:candidate-f1.author",
        "node:candidate-f2.before",
        "node:candidate-f2.after",
        "node:candidate-f3.mutated",
        "node:candidate-f3.fixed",
        "worker",
    }
)
BRIDGE_CHILD_COUNT = len(BRIDGE_CHILD_ROLES)
BRIDGE_SUPERVISION_OVERHEAD_SECONDS = 15.0
BRIDGE_REGISTRATION_LIMIT = 512
BRIDGE_CLEANUP_GRACE_SECONDS = 3.0
BRIDGE_ROLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")


class BridgeGateBlocked(ValueError):
    """The two-process replay cannot emit a green claim."""

    def __init__(
        self,
        message: str,
        *,
        cleanup: dict[str, Any] | None = None,
        observed_runs: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.cleanup = cleanup
        self.observed_runs = observed_runs


def _require_protected_execution_broker() -> None:
    if REGISTERED_PROTECTED_EXECUTION_BROKER_SHA256 is None:
        raise BridgeGateBlocked("production replay requires a protected execution broker authority")
    raise BridgeGateBlocked("protected execution broker transport is not implemented")


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    except (TypeError, ValueError, RecursionError) as error:
        raise BridgeGateBlocked("replay value is not canonical JSON") from error


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def bytes_hash(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def _strict_canonical_path(
    value: str | os.PathLike[str],
    label: str,
    *,
    must_exist: bool,
    directory: bool | None = None,
) -> Path:
    """Reject lexical aliases and every symlink in an external path ancestry."""

    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or raw != os.path.abspath(raw):
        raise BridgeGateBlocked(f"{label} must be a lexical-canonical absolute path")
    candidate = Path(raw)
    cursor = Path(candidate.anchor)
    missing = False
    for part in candidate.parts[1:]:
        cursor /= part
        if missing:
            continue
        try:
            metadata = cursor.lstat()
        except FileNotFoundError:
            missing = True
            continue
        except OSError as error:
            raise BridgeGateBlocked(f"{label} ancestry is unavailable") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise BridgeGateBlocked(f"{label} ancestry contains a symlink")
    if must_exist and missing:
        raise BridgeGateBlocked(f"{label} is unavailable")
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as error:
        raise BridgeGateBlocked(f"{label} is unavailable") from error
    if resolved != candidate:
        raise BridgeGateBlocked(f"{label} is not lexical-canonical")
    if not missing and directory is True and not candidate.is_dir():
        raise BridgeGateBlocked(f"{label} is not a directory")
    if not missing and directory is False and not candidate.is_file():
        raise BridgeGateBlocked(f"{label} is not a file")
    return candidate


_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class _AnchoredDirectory:
    """A directory inode retained independently from its mutable pathname."""

    def __init__(
        self,
        *,
        path: Path,
        descriptor: int,
        label: str,
        mode: int,
        parent_descriptor: int,
        name: str,
        owns_parent_descriptor: bool,
        owned_entry: bool,
    ) -> None:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != mode:
            raise BridgeGateBlocked(f"{label} does not have exact mode {mode:o}")
        self.path = path
        self.descriptor = descriptor
        self.label = label
        self.mode = mode
        self.parent_descriptor = parent_descriptor
        self.name = name
        self.owns_parent_descriptor = owns_parent_descriptor
        self.owned_entry = owned_entry
        self.identity = (metadata.st_dev, metadata.st_ino)
        self.closed = False

    def assert_path_identity(self) -> None:
        if self.closed:
            raise BridgeGateBlocked(f"{self.label} descriptor is closed")
        metadata = os.fstat(self.descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != self.mode
            or (metadata.st_dev, metadata.st_ino) != self.identity
        ):
            raise BridgeGateBlocked(f"{self.label} opened identity changed")
        try:
            path_metadata = os.stat(self.path, follow_symlinks=False)
        except OSError as error:
            raise BridgeGateBlocked(f"{self.label} pathname was replaced") from error
        if (
            not stat.S_ISDIR(path_metadata.st_mode)
            or stat.S_IMODE(path_metadata.st_mode) != self.mode
            or (path_metadata.st_dev, path_metadata.st_ino) != self.identity
        ):
            raise BridgeGateBlocked(f"{self.label} pathname was replaced")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        with contextlib.suppress(OSError):
            os.close(self.descriptor)
        if self.owns_parent_descriptor:
            with contextlib.suppress(OSError):
                os.close(self.parent_descriptor)


def _validate_child_name(name: str, label: str) -> None:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise BridgeGateBlocked(f"{label} name is invalid")


def _open_or_create_secure_root(path: Path, label: str) -> _AnchoredDirectory:
    path = _strict_canonical_path(path, label, must_exist=False, directory=True)
    parent = _strict_canonical_path(
        path.parent,
        f"{label} parent",
        must_exist=True,
        directory=True,
    )
    _validate_child_name(path.name, label)
    parent_descriptor = -1
    descriptor = -1
    created = False
    handle: _AnchoredDirectory | None = None
    try:
        before = parent.lstat()
        parent_descriptor = os.open(parent, _DIRECTORY_OPEN_FLAGS)
        opened_parent = os.fstat(parent_descriptor)
        if not stat.S_ISDIR(before.st_mode) or (before.st_dev, before.st_ino) != (
            opened_parent.st_dev,
            opened_parent.st_ino,
        ):
            raise BridgeGateBlocked(f"{label} parent changed while it was opened")
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent_descriptor)
            created = True
        except FileExistsError:
            pass
        descriptor = os.open(path.name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_descriptor)
        handle = _AnchoredDirectory(
            path=path,
            descriptor=descriptor,
            label=label,
            mode=0o700,
            parent_descriptor=parent_descriptor,
            name=path.name,
            owns_parent_descriptor=True,
            owned_entry=created,
        )
        handle.assert_path_identity()
        descriptor = -1
        parent_descriptor = -1
        return handle
    except BaseException as error:
        if handle is not None:
            handle.close()
            descriptor = -1
            parent_descriptor = -1
        if isinstance(error, BridgeGateBlocked):
            raise
        if isinstance(error, OSError):
            raise BridgeGateBlocked(f"{label} could not be opened securely") from error
        raise
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if parent_descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(parent_descriptor)


def _open_child_directory(
    parent: _AnchoredDirectory,
    name: str,
    label: str,
    *,
    mode: int = 0o700,
    create: bool = True,
    exist_ok: bool = False,
    created_callback: Callable[[], None] | None = None,
) -> _AnchoredDirectory:
    _validate_child_name(name, label)
    created = False
    descriptor = -1
    handle: _AnchoredDirectory | None = None
    try:
        if create:
            try:
                os.mkdir(name, mode, dir_fd=parent.descriptor)
                created = True
                if created_callback is not None:
                    created_callback()
            except FileExistsError:
                if not exist_ok:
                    raise
        descriptor = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent.descriptor)
        handle = _AnchoredDirectory(
            path=parent.path / name,
            descriptor=descriptor,
            label=label,
            mode=mode,
            parent_descriptor=parent.descriptor,
            name=name,
            owns_parent_descriptor=False,
            owned_entry=created,
        )
        descriptor = -1
        return handle
    except BaseException as error:
        if handle is not None:
            handle.close()
            descriptor = -1
        if isinstance(error, BridgeGateBlocked):
            raise
        if isinstance(error, OSError):
            raise BridgeGateBlocked(f"{label} could not be opened securely") from error
        raise
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _create_random_directory(
    parent: _AnchoredDirectory,
    prefix: str,
    label: str,
    *,
    registry: _RetainedHolderRegistry | None = None,
) -> _AnchoredDirectory:
    for _ in range(128):
        name = f"{prefix}{secrets.token_hex(12)}"
        token = registry.intent(name) if registry is not None else None
        handle: _AnchoredDirectory | None = None
        try:
            handle = _open_child_directory(
                parent,
                name,
                label,
                created_callback=(
                    None if token is None else lambda token=token: registry.mark_created(token)
                ),
            )
            if token is not None:
                try:
                    registry.observe(token, handle)
                except BaseException:
                    handle.close()
                    raise
            return handle
        except BridgeGateBlocked as error:
            if isinstance(error.__cause__, FileExistsError):
                if registry is not None and token is not None:
                    registry.cancel(token)
                continue
            if registry is not None and token is not None and not registry.was_created(token):
                registry.cancel(token)
            raise
        except BaseException:
            if handle is not None:
                handle.close()
            raise
    raise BridgeGateBlocked(f"{label} could not allocate a unique name")


def _stat_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _seal_holder_tree(descriptor: int) -> None:
    max_files, max_directories, max_bytes, max_file_bytes = REPLAY_HOLDER_CAPS
    counts = {"files": 0, "directories": 0, "bytes": 0}

    def visit(directory: int) -> None:
        counts["directories"] += 1
        if counts["directories"] > max_directories:
            raise BridgeGateBlocked("replay holder directory count exceeds its cap")
        try:
            names = sorted(os.listdir(directory), key=lambda item: item.encode("utf-8"))
        except (OSError, UnicodeEncodeError) as error:
            raise BridgeGateBlocked("replay holder cannot be enumerated") from error
        for name in names:
            _safe_path(name, "replay holder entry")
            before = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISDIR(before.st_mode):
                flags = _DIRECTORY_OPEN_FLAGS
            elif stat.S_ISREG(before.st_mode):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
            else:
                raise BridgeGateBlocked("replay holder contains a non-regular entry")
            child = -1
            try:
                child = os.open(name, flags, dir_fd=directory)
                opened = os.fstat(child)
                if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                    raise BridgeGateBlocked("replay holder entry changed while opened")
                if stat.S_ISDIR(opened.st_mode):
                    visit(child)
                    os.fchmod(child, 0o555)
                else:
                    if opened.st_nlink != 1:
                        raise BridgeGateBlocked("replay holder contains a hard-linked file")
                    counts["files"] += 1
                    counts["bytes"] += opened.st_size
                    if (
                        counts["files"] > max_files
                        or counts["bytes"] > max_bytes
                        or opened.st_size > max_file_bytes
                    ):
                        raise BridgeGateBlocked("replay holder file or aggregate exceeds its cap")
                    os.fchmod(child, 0o444)
                after = os.stat(name, dir_fd=directory, follow_symlinks=False)
                retained = os.fstat(child)
                if (after.st_dev, after.st_ino) != (retained.st_dev, retained.st_ino):
                    raise BridgeGateBlocked("replay holder entry changed while sealed")
            except OSError as error:
                raise BridgeGateBlocked("replay holder could not be sealed") from error
            finally:
                if child >= 0:
                    with contextlib.suppress(OSError):
                        os.close(child)

    visit(descriptor)
    try:
        os.fchmod(descriptor, 0o555)
    except OSError as error:
        raise BridgeGateBlocked("replay holder root could not be sealed") from error


def _snapshot_holder_tree(
    descriptor: int,
    *,
    kind: str,
    caps: tuple[int, int, int, int] = REPLAY_HOLDER_CAPS,
) -> tuple[bytes, dict[str, int]]:
    file_modes = {
        "production-process-root": 0o444,
        "production-runtime-root": 0o555,
        "production-trusted-root": 0o444,
        "replay-holder-root": 0o444,
        "qualification-publication-partial-root": 0o444,
    }
    try:
        expected_file_mode = file_modes[kind]
    except KeyError as error:
        raise BridgeGateBlocked("retained root kind has no registered file mode") from error
    max_files, max_directories, max_bytes, max_file_bytes = caps
    rows: list[bytes] = []
    counts = {"files": 0, "directories": 0, "bytes": 0}

    def row(path: str, entry_type: str, mode: int, size: int, digest: str) -> bytes:
        return (
            path.encode("utf-8")
            + b"\0"
            + entry_type.encode("ascii")
            + b"\0"
            + f"{mode:04o}".encode("ascii")
            + b"\0"
            + str(size).encode("ascii")
            + b"\0"
            + digest.encode("ascii")
            + b"\n"
        )

    def visit(directory: int, prefix: PurePosixPath | None) -> None:
        root = os.fstat(directory)
        if not stat.S_ISDIR(root.st_mode) or stat.S_IMODE(root.st_mode) != 0o555:
            raise BridgeGateBlocked("replay holder directory is not sealed")
        counts["directories"] += 1
        if counts["directories"] > max_directories:
            raise BridgeGateBlocked("replay holder directory count exceeds its cap")
        rendered_root = "." if prefix is None else prefix.as_posix()
        rows.append(row(rendered_root, "directory", 0o555, 0, hashlib.sha256(b"").hexdigest()))
        for name in sorted(os.listdir(directory), key=lambda item: item.encode("utf-8")):
            relative = PurePosixPath(name) if prefix is None else prefix / name
            rendered = _safe_path(relative.as_posix(), "replay holder roster path").as_posix()
            before = os.stat(name, dir_fd=directory, follow_symlinks=False)
            flags = (
                _DIRECTORY_OPEN_FLAGS
                if stat.S_ISDIR(before.st_mode)
                else os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
            )
            if not (stat.S_ISDIR(before.st_mode) or stat.S_ISREG(before.st_mode)):
                raise BridgeGateBlocked("replay holder contains a non-regular entry")
            child = -1
            try:
                child = os.open(name, flags, dir_fd=directory)
                opened = os.fstat(child)
                if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                    raise BridgeGateBlocked("replay holder entry changed while opened")
                if stat.S_ISDIR(opened.st_mode):
                    visit(child, relative)
                else:
                    if stat.S_IMODE(opened.st_mode) != expected_file_mode or opened.st_nlink != 1:
                        raise BridgeGateBlocked("replay holder regular file is not sealed")
                    if opened.st_size > max_file_bytes:
                        raise BridgeGateBlocked("retained root file or aggregate exceeds its cap")
                    chunks: list[bytes] = []
                    remaining = opened.st_size
                    while remaining:
                        chunk = os.read(child, min(64 * 1024, remaining))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    raw = b"".join(chunks)
                    retained = os.fstat(child)
                    after = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    if (
                        len(raw) != opened.st_size
                        or _stat_identity(opened) != _stat_identity(retained)
                        or (after.st_dev, after.st_ino) != (retained.st_dev, retained.st_ino)
                    ):
                        raise BridgeGateBlocked("replay holder file changed during snapshot")
                    counts["files"] += 1
                    counts["bytes"] += len(raw)
                    if counts["files"] > max_files or counts["bytes"] > max_bytes:
                        raise BridgeGateBlocked("retained root file or aggregate exceeds its cap")
                    rows.append(
                        row(
                            rendered,
                            "regular",
                            expected_file_mode,
                            len(raw),
                            hashlib.sha256(raw).hexdigest(),
                        )
                    )
            except OSError as error:
                raise BridgeGateBlocked("replay holder could not be snapshotted") from error
            finally:
                if child >= 0:
                    with contextlib.suppress(OSError):
                        os.close(child)

    visit(descriptor, None)
    return b"".join(rows), counts


def _holder_change_witness(descriptor: int) -> str:
    rows: list[tuple[Any, ...]] = []

    def visit(directory: int, prefix: PurePosixPath | None) -> None:
        metadata = os.fstat(directory)
        rendered = "." if prefix is None else prefix.as_posix()
        rows.append((rendered, *_stat_identity(metadata)))
        for name in sorted(os.listdir(directory), key=lambda item: item.encode("utf-8")):
            relative = PurePosixPath(name) if prefix is None else prefix / name
            _safe_path(relative.as_posix(), "replay holder witness path")
            before = os.stat(name, dir_fd=directory, follow_symlinks=False)
            child = -1
            try:
                if stat.S_ISDIR(before.st_mode):
                    child = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=directory)
                    opened = os.fstat(child)
                    if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                        raise BridgeGateBlocked("replay holder changed during witness")
                    visit(child, relative)
                elif stat.S_ISREG(before.st_mode):
                    rows.append((relative.as_posix(), *_stat_identity(before)))
                else:
                    raise BridgeGateBlocked("replay holder witness found a special entry")
            except OSError as error:
                raise BridgeGateBlocked("replay holder change witness failed") from error
            finally:
                if child >= 0:
                    with contextlib.suppress(OSError):
                        os.close(child)

    visit(descriptor, None)
    return canonical_hash(rows)


def _holder_descriptor(
    descriptor: int,
    handle: _AnchoredDirectory,
    locator: str,
) -> dict[str, Any]:
    locator = _safe_path(locator, "replay holder locator").as_posix()
    _seal_holder_tree(descriptor)
    handle.mode = 0o555
    witness_before = _holder_change_witness(descriptor)
    first, counts = _snapshot_holder_tree(descriptor, kind="replay-holder-root")
    witness_middle = _holder_change_witness(descriptor)
    second, second_counts = _snapshot_holder_tree(descriptor, kind="replay-holder-root")
    witness_after = _holder_change_witness(descriptor)
    if (
        first != second
        or counts != second_counts
        or len({witness_before, witness_middle, witness_after}) != 1
    ):
        raise BridgeGateBlocked("replay holder changed between retained snapshots")
    digest = bytes_hash(first)
    body = {
        "state": "sealed",
        "kind": "replay-holder-root",
        "logical_root": "replay-holder",
        "anchor": "replay-artifact-root",
        "locator": locator,
        "counts": counts,
        "physical_roster_sha256": digest,
        "normalized_roster_sha256": digest,
        "snapshot_first_sha256": digest,
        "snapshot_second_sha256": digest,
        "sealed": True,
    }
    return {**body, "root_id": canonical_hash(body)}


def _empty_cleanup() -> dict[str, Any]:
    return {
        "status": "cleanup_deferred",
        "gc_policy": GC_POLICY,
        "delete_attempts": 0,
        "retained_roots": [],
    }


def _remove_owned_directory(handle: _AnchoredDirectory) -> bool:
    """Compatibility shim: close the FD and deliberately retain the owned entry."""

    handle.close()
    return False


class _RetainedHolderRegistry:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def intent(self, locator: str) -> int:
        locator = _safe_path(locator, "replay holder intent locator").as_posix()
        self.entries.append(
            {
                "locator": locator,
                "descriptor": -1,
                "handle": None,
                "active": True,
                "creation_observed": False,
                "descriptor_observed": False,
            }
        )
        return len(self.entries) - 1

    def cancel(self, token: int) -> None:
        entry = self.entries[token]
        if entry["creation_observed"]:
            raise BridgeGateBlocked("observed replay holder intent cannot be cancelled")
        entry["active"] = False

    def mark_created(self, token: int) -> None:
        entry = self.entries[token]
        if entry["creation_observed"]:
            raise BridgeGateBlocked("replay holder creation was observed twice")
        entry["creation_observed"] = True

    def was_created(self, token: int) -> bool:
        return bool(self.entries[token]["creation_observed"])

    def observe(self, token: int, handle: _AnchoredDirectory) -> None:
        entry = self.entries[token]
        if not entry["creation_observed"] or entry["descriptor_observed"]:
            raise BridgeGateBlocked("replay holder intent was observed out of order")
        descriptor = -1
        try:
            descriptor = os.dup(handle.descriptor)
            entry["descriptor"] = descriptor
            entry["handle"] = handle
            entry["descriptor_observed"] = True
        except BaseException as error:
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
            dict.__setitem__(entry, "descriptor", -1)
            dict.__setitem__(entry, "handle", None)
            dict.__setitem__(entry, "descriptor_observed", False)
            if isinstance(error, OSError):
                raise BridgeGateBlocked("replay holder descriptor could not be retained") from error
            raise

    def cleanup(self, *, qualified: bool) -> dict[str, Any]:
        roots: list[dict[str, Any]] = []
        for entry in self.entries:
            if not entry["active"]:
                continue
            if not entry["creation_observed"]:
                continue
            if not entry["descriptor_observed"]:
                if qualified:
                    raise BridgeGateBlocked(
                        "replay holder creation did not yield a retained descriptor"
                    )
                body = {
                    "state": "unmeasurable",
                    "kind": "replay-holder-root",
                    "logical_root": "replay-holder",
                    "anchor": "replay-artifact-root",
                    "locator": entry["locator"],
                    "creation_observed": True,
                    "reason": "creation attempt did not yield a retained descriptor",
                }
                roots.append({**body, "root_id": canonical_hash(body)})
                continue
            try:
                roots.append(
                    _holder_descriptor(
                        entry["descriptor"],
                        entry["handle"],
                        entry["locator"],
                    )
                )
            except Exception as error:
                if qualified:
                    raise BridgeGateBlocked(
                        "replay holder could not be sealed and measured"
                    ) from error
                body = {
                    "state": "unmeasurable",
                    "kind": "replay-holder-root",
                    "logical_root": "replay-holder",
                    "anchor": "replay-artifact-root",
                    "locator": entry["locator"],
                    "creation_observed": True,
                    "reason": str(error)[:512] or "replay holder measurement failed",
                }
                roots.append({**body, "root_id": canonical_hash(body)})
        return {
            "status": "cleanup_deferred",
            "gc_policy": GC_POLICY,
            "delete_attempts": 0,
            "retained_roots": roots,
        }

    def close(self) -> None:
        for entry in self.entries:
            if entry["descriptor"] >= 0:
                with contextlib.suppress(OSError):
                    os.close(entry["descriptor"])
                entry["descriptor"] = -1


def _validate_cleanup(
    value: Any,
    *,
    qualified: bool,
    expected_kinds: tuple[str, ...] | None = None,
    blocked_prefixes: tuple[tuple[str, ...], ...] | None = None,
) -> dict[str, Any]:
    cleanup = _exact(
        value,
        {"status", "gc_policy", "delete_attempts", "retained_roots"},
        "retained cleanup",
    )
    if (
        cleanup["status"] != "cleanup_deferred"
        or cleanup["gc_policy"] != GC_POLICY
        or type(cleanup["delete_attempts"]) is not int
        or cleanup["delete_attempts"] != 0
        or not isinstance(cleanup["retained_roots"], list)
    ):
        raise BridgeGateBlocked("retained cleanup contract is invalid")
    roots = cleanup["retained_roots"]
    observed_kinds = tuple(root.get("kind") if isinstance(root, dict) else None for root in roots)
    if qualified and expected_kinds is not None and observed_kinds != expected_kinds:
        raise BridgeGateBlocked("qualified retained root order is invalid")
    if not qualified and blocked_prefixes is not None and observed_kinds not in blocked_prefixes:
        raise BridgeGateBlocked("blocked retained root order is invalid")
    expected_identity = {
        "production-process-root": ("process", "run-root"),
        "production-runtime-root": ("runtime", "run-root"),
        "production-trusted-root": ("trusted", "run-root"),
        "qualification-publication-partial-root": (
            "qualification-publication-partial",
            "artifact-root",
        ),
        "replay-holder-root": ("replay-holder", "replay-artifact-root"),
    }
    seen_ids: set[str] = set()
    seen_logical: set[tuple[str, str]] = set()
    for index, value_root in enumerate(roots):
        if not isinstance(value_root, dict):
            raise BridgeGateBlocked("retained root descriptor is invalid")
        state = value_root.get("state")
        if state == "sealed":
            root = _exact(
                value_root,
                {
                    "state",
                    "kind",
                    "logical_root",
                    "anchor",
                    "locator",
                    "counts",
                    "physical_roster_sha256",
                    "normalized_roster_sha256",
                    "snapshot_first_sha256",
                    "snapshot_second_sha256",
                    "sealed",
                    "root_id",
                },
                f"sealed retained root {index}",
            )
            counts = _exact(root["counts"], {"files", "directories", "bytes"}, "root counts")
            if (
                root["sealed"] is not True
                or any(type(counts[name]) is not int or counts[name] < 0 for name in counts)
                or counts["directories"] < 1
                or any(
                    not _valid_hash(root[name])
                    for name in (
                        "physical_roster_sha256",
                        "normalized_roster_sha256",
                        "snapshot_first_sha256",
                        "snapshot_second_sha256",
                        "root_id",
                    )
                )
                or not (
                    root["physical_roster_sha256"]
                    == root["normalized_roster_sha256"]
                    == root["snapshot_first_sha256"]
                    == root["snapshot_second_sha256"]
                )
            ):
                raise BridgeGateBlocked("sealed retained root is invalid")
        elif state == "unmeasurable" and not qualified:
            root = _exact(
                value_root,
                {
                    "state",
                    "kind",
                    "logical_root",
                    "anchor",
                    "locator",
                    "creation_observed",
                    "reason",
                    "root_id",
                },
                f"unmeasurable retained root {index}",
            )
            if (
                root["creation_observed"] is not True
                or not isinstance(root["reason"], str)
                or not root["reason"]
                or len(root["reason"]) > 512
                or not _valid_hash(root["root_id"])
            ):
                raise BridgeGateBlocked("unmeasurable retained root is invalid")
        else:
            raise BridgeGateBlocked("retained root state is invalid")
        kind = root["kind"]
        if kind not in expected_identity:
            raise BridgeGateBlocked("retained root kind is invalid")
        if state == "sealed":
            max_files, max_directories, max_bytes = RETAINED_ROOT_CAPS[kind]
            if (
                root["counts"]["files"] > max_files
                or root["counts"]["directories"] > max_directories
                or root["counts"]["bytes"] > max_bytes
            ):
                raise BridgeGateBlocked("retained root counts exceed their cap")
        logical_root, anchor = expected_identity[kind]
        if root["logical_root"] != logical_root or root["anchor"] != anchor:
            raise BridgeGateBlocked("retained root kind binding is invalid")
        _safe_path(root["locator"], "retained root locator")
        body = {key: item for key, item in root.items() if key != "root_id"}
        if root["root_id"] != canonical_hash(body):
            raise BridgeGateBlocked("retained root id is invalid")
        logical_key = (kind, root["logical_root"])
        if root["root_id"] in seen_ids or logical_key in seen_logical:
            raise BridgeGateBlocked("retained root descriptor is duplicated")
        seen_ids.add(root["root_id"])
        seen_logical.add(logical_key)
    return cleanup


def _normalized_qualification_projection(report: dict[str, Any]) -> dict[str, Any]:
    projection = json.loads(canonical_json_bytes(report))
    projection.pop("manifest_sha256", None)
    cleanup = projection.get("cleanup")
    if not isinstance(cleanup, dict) or not isinstance(cleanup.get("retained_roots"), list):
        raise BridgeGateBlocked("qualification cleanup projection is unavailable")
    for root in cleanup["retained_roots"]:
        if not isinstance(root, dict):
            raise BridgeGateBlocked("qualification cleanup projection is invalid")
        root["locator"] = ""
        for field in (
            "physical_roster_sha256",
            "snapshot_first_sha256",
            "snapshot_second_sha256",
            "root_id",
        ):
            if field in root:
                root[field] = ZERO_HASH
    return projection


def _validate_observed_runs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 2:
        raise BridgeGateBlocked("blocked replay observed-run roster is invalid")
    for index, item in enumerate(value, start=1):
        row = _exact(
            item,
            {
                "run_index",
                "status",
                "qualification_manifest_sha256",
                "report_bytes_sha256",
                "cleanup",
            },
            f"blocked replay observed run {index}",
        )
        if type(row["run_index"]) is not int or row["run_index"] != index:
            raise BridgeGateBlocked("blocked replay observed-run order is invalid")
        if row["status"] == "qualified":
            if not _valid_hash(row["qualification_manifest_sha256"]) or not _valid_hash(
                row["report_bytes_sha256"]
            ):
                raise BridgeGateBlocked("qualified observed-run digests are invalid")
            _validate_cleanup(
                row["cleanup"],
                qualified=True,
                expected_kinds=(
                    "production-process-root",
                    "production-runtime-root",
                    "production-trusted-root",
                ),
            )
        elif row["status"] == "blocked":
            if row["qualification_manifest_sha256"] is not None or not _valid_hash(
                row["report_bytes_sha256"]
            ):
                raise BridgeGateBlocked("blocked observed-run digests are invalid")
            _validate_cleanup(
                row["cleanup"],
                qualified=False,
                blocked_prefixes=BLOCKED_CHILD_RETAINED_PREFIXES,
            )
        elif row["status"] == "no-report":
            if any(
                row[name] is not None
                for name in (
                    "qualification_manifest_sha256",
                    "report_bytes_sha256",
                    "cleanup",
                )
            ):
                raise BridgeGateBlocked("no-report observed-run evidence is overstated")
        else:
            raise BridgeGateBlocked("blocked replay observed-run status is invalid")
    return value


def _read_regular_at(
    directory_descriptor: int,
    name: str,
    limit: int,
    label: str,
    *,
    mode: int,
) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_descriptor,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != mode
            or before.st_size > limit
        ):
            raise BridgeGateBlocked(f"{label} identity, mode, or size is invalid")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) != before.st_size
            or len(raw) > limit
            or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
                before.st_mode,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
                after.st_mode,
            )
        ):
            raise BridgeGateBlocked(f"{label} changed while it was read")
        return raw
    except BridgeGateBlocked:
        raise
    except OSError as error:
        raise BridgeGateBlocked(f"{label} could not be read securely") from error
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _expected_tree_directories(files: set[str]) -> set[str]:
    return {
        parent.as_posix()
        for name in files
        for parent in PurePosixPath(name).parents
        if parent.as_posix() != "."
    }


def _snapshot_publication_descriptor(
    root_descriptor: int,
    expected_files: set[str],
) -> dict[str, bytes]:
    root_metadata = os.fstat(root_descriptor)
    if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_IMODE(root_metadata.st_mode) != 0o555:
        raise BridgeGateBlocked("fresh qualification publication is not immutable")
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    snapshot: dict[str, bytes] = {}
    total = 0

    def visit(descriptor: int, prefix: PurePosixPath | None = None) -> None:
        nonlocal total
        try:
            names = sorted(os.listdir(descriptor))
        except OSError as error:
            raise BridgeGateBlocked("fresh qualification tree could not be listed") from error
        for name in names:
            _validate_child_name(name, "fresh qualification tree entry")
            relative = PurePosixPath(name) if prefix is None else prefix / name
            try:
                metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except OSError as error:
                raise BridgeGateBlocked("fresh qualification tree changed") from error
            if stat.S_ISLNK(metadata.st_mode):
                raise BridgeGateBlocked("fresh qualification tree contains a symlink")
            if stat.S_ISDIR(metadata.st_mode):
                if stat.S_IMODE(metadata.st_mode) != 0o555:
                    raise BridgeGateBlocked("fresh qualification directory is not immutable")
                actual_directories.add(relative.as_posix())
                child = -1
                try:
                    child = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
                    visit(child, relative)
                except OSError as error:
                    raise BridgeGateBlocked(
                        "fresh qualification directory could not be opened securely"
                    ) from error
                finally:
                    if child >= 0:
                        os.close(child)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise BridgeGateBlocked("fresh qualification tree contains an invalid entry")
            relative_name = relative.as_posix()
            actual_files.add(relative_name)
            limit = (
                MAX_REPORT_BYTES if relative_name == "qualification.json" else MAX_ARTIFACT_BYTES
            )
            raw = _read_regular_at(
                descriptor,
                name,
                limit,
                f"fresh qualification file {relative_name}",
                mode=0o444,
            )
            total += len(raw)
            if total > MAX_PUBLISHED_BYTES:
                raise BridgeGateBlocked("fresh qualification tree exceeds its aggregate cap")
            snapshot[relative_name] = raw

    visit(root_descriptor)
    if actual_files != expected_files or actual_directories != _expected_tree_directories(
        expected_files
    ):
        raise BridgeGateBlocked("fresh qualification artifact roster is not exact")
    return snapshot


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise BridgeGateBlocked(f"JSON contains duplicate key {key!r}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise BridgeGateBlocked(f"JSON contains non-finite constant {value}")


def _decode_canonical(raw: bytes, label: str) -> Any:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise BridgeGateBlocked(f"{label} is not valid JSON") from error
    if raw != canonical_json_bytes(value):
        raise BridgeGateBlocked(f"{label} is not canonical JSON")
    return value


def _exact(value: Any, keys: set[str] | frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise BridgeGateBlocked(f"{label} fields drifted")
    return value


def _manifest_hash(value: Any, label: str) -> str:
    if not isinstance(value, dict) or "manifest_sha256" not in value:
        raise BridgeGateBlocked(f"{label} is missing its digest")
    body = {key: item for key, item in value.items() if key != "manifest_sha256"}
    measured = canonical_hash(body)
    if value["manifest_sha256"] != measured:
        raise BridgeGateBlocked(f"{label} digest is invalid")
    return measured


def _exact_count_map(value: Any, expected: dict[str, int], label: str) -> None:
    counts = _exact(value, set(expected), label)
    if counts != expected or any(type(item) is not int for item in counts.values()):
        raise BridgeGateBlocked(f"{label} drifted")


def _validate_file_rows(value: Any, label: str) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(value, list) or not value:
        raise BridgeGateBlocked(f"{label} roster is empty")
    seen: set[str] = set()
    total = 0
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        row = _exact(raw, {"path", "size", "mode", "sha256", "role"}, f"{label} row {index}")
        path = _safe_path(row["path"], f"{label} row {index} path")
        lowered = {part.lower() for part in path.parts}
        if (
            path.as_posix() in seen
            or ".git" in lowered
            or any(part == ".env" or part.startswith(".env.") for part in lowered)
            or type(row["size"]) is not int
            or row["size"] < 0
            or type(row["mode"]) is not int
            or row["mode"] not in {0o444, 0o555}
            or not _valid_hash(row["sha256"])
            or not isinstance(row["role"], str)
            or not row["role"]
        ):
            raise BridgeGateBlocked(f"{label} row {index} is invalid")
        seen.add(path.as_posix())
        total += row["size"]
        rows.append(row)
    return rows, total


def _validate_tree_descriptor(value: Any, *, kind: str) -> dict[str, Any]:
    keys = {
        "schema_version",
        "bundle_id",
        "kind",
        "counts",
        "files",
        "roster_sha256",
        "manifest_sha256",
    }
    if kind == "dependency":
        keys.add("python")
    descriptor = _exact(value, keys, f"{kind} bundle authority")
    if (
        type(descriptor["schema_version"]) is not int
        or descriptor["schema_version"] != 3
        or not isinstance(descriptor["bundle_id"], str)
        or not descriptor["bundle_id"]
        or descriptor["kind"] != kind
    ):
        raise BridgeGateBlocked(f"{kind} bundle identity is invalid")
    rows, total = _validate_file_rows(descriptor["files"], f"{kind} bundle")
    if any(row["path"] in {"bundle.json", "capsule.json"} for row in rows):
        raise BridgeGateBlocked(f"{kind} bundle roster includes its manifest")
    _exact_count_map(
        descriptor["counts"], {"files": len(rows), "bytes": total}, f"{kind} bundle counts"
    )
    _manifest_hash(descriptor, f"{kind} bundle authority")
    if kind == "source":
        if descriptor["roster_sha256"] != canonical_hash(rows):
            raise BridgeGateBlocked("source bundle roster digest is invalid")
    elif (
        descriptor["python"] != DEPENDENCY_PYTHON
        or len(rows) != 144
        or total != 1_799_002
        or descriptor["roster_sha256"] != DEPENDENCY_ROSTER_SHA256
    ):
        raise BridgeGateBlocked("dependency bundle ABI or denominator drifted")
    return descriptor


def _validate_capsule(value: Any) -> dict[str, Any]:
    capsule = _exact(
        value,
        {
            "schema_version",
            "capsule_id",
            "revision",
            "tree",
            "language_version",
            "loader",
            "runner",
            "tooling",
            "counts",
            "files",
            "roster_sha256",
            "manifest_sha256",
        },
        "capsule authority",
    )
    if (
        type(capsule["schema_version"]) is not int
        or capsule["schema_version"] != 3
        or not isinstance(capsule["capsule_id"], str)
        or not capsule["capsule_id"]
        or capsule["revision"] != PINNED_METIS_REVISION
        or capsule["tree"] != PINNED_METIS_TREE
        or capsule["language_version"] != "0.43"
    ):
        raise BridgeGateBlocked("capsule identity drifted")
    rows, total = _validate_file_rows(capsule["files"], "capsule")
    if any(
        row["path"] == "capsule.json"
        or row["role"] not in {"git-archive", "tooling", "loader", "runner"}
        for row in rows
    ):
        raise BridgeGateBlocked("capsule file roster contains an invalid path or role")
    by_path = {row["path"]: row for row in rows}
    _exact_count_map(capsule["counts"], {"files": len(rows), "bytes": total}, "capsule counts")
    if capsule["roster_sha256"] != canonical_hash(rows) or capsule["tooling"] != PINNED_TOOLING:
        raise BridgeGateBlocked("capsule roster or tooling drifted")
    for role in ("loader", "runner"):
        identity = _exact(capsule[role], {"path", "sha256", "mode"}, f"capsule {role}")
        _safe_path(identity["path"], f"capsule {role} path")
        row = by_path.get(identity["path"])
        if (
            row is None
            or row["role"] != role
            or row["sha256"] != identity["sha256"]
            or row["mode"] != identity["mode"]
        ):
            raise BridgeGateBlocked(f"capsule {role} identity is not bound into its roster")
    if capsule["loader"] != {
        "path": ".metis-oracle/native_ts_loader.mjs",
        "sha256": PINNED_LOADER_SHA256,
        "mode": 0o444,
    }:
        raise BridgeGateBlocked("capsule loader identity drifted")
    if capsule["runner"] != {
        "path": ".metis-oracle/runner.ts",
        "sha256": PINNED_RUNNER_SHA256,
        "mode": 0o444,
    }:
        raise BridgeGateBlocked("capsule runner identity drifted")
    _manifest_hash(capsule, "capsule authority")
    return capsule


def _read_regular(path: Path, limit: int, label: str) -> bytes:
    try:
        before = path.lstat()
    except OSError as error:
        raise BridgeGateBlocked(f"{label} is unavailable") from error
    if path.is_symlink() or not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise BridgeGateBlocked(f"{label} is not a bounded regular file")
    raw = path.read_bytes()
    after = path.lstat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_mode) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_mode,
    ) or len(raw) != before.st_size:
        raise BridgeGateBlocked(f"{label} changed while read")
    return raw


def _measured_launcher(
    qualifier: Path,
    qualifier_sha256: str,
    python: Path,
) -> dict[str, Any]:
    sandbox = Path("/usr/bin/sandbox-exec")
    try:
        sandbox = sandbox.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise BridgeGateBlocked("sandbox executable is unavailable") from error
    if sandbox.is_symlink() or str(sandbox) != "/usr/bin/sandbox-exec":
        raise BridgeGateBlocked("sandbox executable identity drifted")
    version = sys.version_info
    python_version = f"{version.major}.{version.minor}.{version.micro}"
    if python_version != DEPENDENCY_PYTHON["version"]:
        raise BridgeGateBlocked("bridge requires the registered CPython version")
    return {
        "qualifier_path": str(qualifier),
        "qualifier_sha256": qualifier_sha256,
        "python_executable": str(python),
        "python_executable_sha256": bytes_hash(
            _read_regular(python, MAX_EXECUTABLE_BYTES, "Python executable")
        ),
        "python_version": python_version,
        "required_flags": ["-I", "-S", "-B"],
        "sandbox_exec_path": str(sandbox),
        "sandbox_exec_sha256": bytes_hash(
            _read_regular(sandbox, MAX_EXECUTABLE_BYTES, "sandbox executable")
        ),
        "sandbox_policy_template_sha256": PINNED_LAUNCHER_POLICY_SHA256,
        "qualifier_bootstrap_sha256": QUALIFIER_BOOTSTRAP_SHA256,
    }


def _load_authority(
    path: Path,
    expected_sha256: str,
    launcher: dict[str, Any],
) -> dict[str, Any]:
    path = _strict_canonical_path(
        path,
        "production authority manifest",
        must_exist=True,
        directory=False,
    )
    if not _valid_hash(expected_sha256):
        raise BridgeGateBlocked("replay authority digest is invalid")
    raw = _read_regular(path, MAX_REPORT_BYTES, "production authority manifest")
    authority = _decode_canonical(raw, "production authority manifest")
    authority = _exact(
        authority,
        {
            "schema_version",
            "authority_id",
            "status",
            "ratification",
            "project",
            "source_bundle",
            "dependency_bundle",
            "capsule",
            "runtime",
            "expected",
            "native_evidence",
            "non_claims",
            "manifest_sha256",
        },
        "production authority manifest",
    )
    if (
        type(authority["schema_version"]) is not int
        or authority["schema_version"] != 3
        or authority["authority_id"] != AUTHORITY_ID
        or authority["status"] != "independently_ratified"
        or _manifest_hash(authority, "production authority manifest") != expected_sha256
    ):
        raise BridgeGateBlocked("production authority identity or digest drifted")
    ratification = _exact(
        authority["ratification"],
        {"verdict", "scope", "independent", "kimi_report_sha256"},
        "production authority ratification",
    )
    if (
        ratification["verdict"] != "RATIFIABLE"
        or ratification["scope"] != ["F-1", "F-2", "F-3"]
        or ratification["independent"] is not True
        or ratification["kimi_report_sha256"] != KIMI_REPORT_SHA256
    ):
        raise BridgeGateBlocked("production authority does not bind the Kimi report")
    project = _exact(
        authority["project"],
        {"revision", "candidate_manifest", "semantic_registry", "launcher", "worker"},
        "production authority project",
    )
    if project["revision"] != PROJECT_REVISION:
        raise BridgeGateBlocked("production authority project revision drifted")
    candidate = _exact(
        project["candidate_manifest"], {"path", "manifest_sha256"}, "candidate manifest"
    )
    registry = _exact(
        project["semantic_registry"], {"path", "manifest_sha256"}, "semantic registry"
    )
    _safe_path(candidate["path"], "candidate manifest path")
    _safe_path(registry["path"], "semantic registry path")
    if candidate["manifest_sha256"] != CANDIDATE_MANIFEST_SHA256:
        raise BridgeGateBlocked("candidate manifest pin drifted")
    if registry["manifest_sha256"] != SEMANTIC_REGISTRY_SHA256:
        raise BridgeGateBlocked("semantic registry pin drifted")
    if _exact(project["launcher"], LAUNCHER_KEYS, "production launcher") != launcher:
        raise BridgeGateBlocked("production launcher differs from measured bridge authority")
    worker = _exact(project["worker"], {"path", "sha256", "protocol"}, "production worker")
    _safe_path(worker["path"], "production worker path")
    if worker["protocol"] != "w3-production-capsule-worker-v3" or not _valid_hash(worker["sha256"]):
        raise BridgeGateBlocked("production worker identity is invalid")
    source = _validate_tree_descriptor(authority["source_bundle"], kind="source")
    _validate_tree_descriptor(authority["dependency_bundle"], kind="dependency")
    _validate_capsule(authority["capsule"])
    runtime = _exact(
        authority["runtime"], {"schema_version", "node", "loader_flags"}, "runtime authority"
    )
    node = _exact(
        runtime["node"], {"path", "size", "source_mode", "mode", "sha256"}, "runtime Node"
    )
    if (
        type(runtime["schema_version"]) is not int
        or runtime["schema_version"] != SCHEMA_VERSION
        or node
        != {
            "path": "bin/node",
            "size": PINNED_NODE_BYTES,
            "source_mode": 0o755,
            "mode": 0o555,
            "sha256": PINNED_NODE_SHA256,
        }
        or runtime["loader_flags"] != PINNED_LOADER_FLAGS
    ):
        raise BridgeGateBlocked("runtime Node preimage or loader flags drifted")
    source_by_path = {row["path"]: row for row in source["files"]}
    if (
        worker["path"] not in source_by_path
        or candidate["path"] not in source_by_path
        or registry["path"] not in source_by_path
        or source_by_path[worker["path"]]["sha256"] != worker["sha256"]
    ):
        raise BridgeGateBlocked("source bundle does not bind its required authority files")
    expected = _exact(
        authority["expected"],
        {"candidates", "executions", "roles"},
        "authority expected roster",
    )
    _exact_count_map(expected["roles"], ONE_RUN_ROLES, "authority expected roles")
    if (
        type(expected["candidates"]) is not int
        or type(expected["executions"]) is not int
        or expected != {"candidates": 3, "executions": 5, "roles": ONE_RUN_ROLES}
    ):
        raise BridgeGateBlocked("production authority roster is not exact")
    if authority["non_claims"] != NON_CLAIMS:
        raise BridgeGateBlocked("production authority overstates its scope")
    if authority["native_evidence"] != NATIVE_EVIDENCE:
        raise BridgeGateBlocked("production authority native evidence binding drifted")
    return authority


def _safe_path(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BridgeGateBlocked(f"{label} is not a safe relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise BridgeGateBlocked(f"{label} is not a safe relative path")
    return path


def _validate_qualification(
    report: Any,
    authority: dict[str, Any],
    authority_sha256: str,
) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise BridgeGateBlocked("qualification report is not an object")
    if set(report) != QUALIFIED_CHILD_REPORT_KEYS:
        raise BridgeGateBlocked("qualification report fields drifted")
    if (
        type(report["schema_version"]) is not int
        or report["schema_version"] != 3
        or report["qualification_id"] != QUALIFICATION_ID
        or report["qualification_kind"] != "production-capsule-v3"
        or report["status"] != "qualified"
        or report["claim"] != "three_ratified_smoke_specs_production_capsule_only_no_accuracy_claim"
        or report["authority_manifest_sha256"] != authority_sha256
        or report["ratification_evidence_sha256"] != KIMI_REPORT_SHA256
        or report["project_revision"] != PROJECT_REVISION
        or report["source_bundle_manifest_sha256"] != authority["source_bundle"]["manifest_sha256"]
        or report["dependency_bundle_manifest_sha256"]
        != authority["dependency_bundle"]["manifest_sha256"]
        or report["candidate_manifest_sha256"] != CANDIDATE_MANIFEST_SHA256
        or report["semantic_registry_sha256"] != SEMANTIC_REGISTRY_SHA256
        or report["dependency_roster_sha256"] != DEPENDENCY_ROSTER_SHA256
        or report["capsule_manifest_sha256"] != authority["capsule"]["manifest_sha256"]
        or report["launcher"] != authority["project"]["launcher"]
        or report["native_evidence"] != NATIVE_EVIDENCE
        or report["non_claims"] != NON_CLAIMS
        or not isinstance(report["executions"], list)
        or len(report["executions"]) != 5
    ):
        raise BridgeGateBlocked("qualification report denominator or claim is invalid")
    _exact_count_map(
        report["counts"],
        {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0},
        "qualification report counts",
    )
    _exact_count_map(report["roles"], ONE_RUN_ROLES, "qualification report roles")
    _validate_cleanup(
        report["cleanup"],
        qualified=True,
        expected_kinds=(
            "production-process-root",
            "production-runtime-root",
            "production-trusted-root",
        ),
    )
    for field in (
        "authority_manifest_sha256",
        "ratification_evidence_sha256",
        "source_bundle_manifest_sha256",
        "dependency_bundle_manifest_sha256",
        "capsule_manifest_sha256",
        "candidate_manifest_sha256",
        "semantic_registry_sha256",
        "worker_input_sha256",
        "worker_output_sha256",
        "manifest_sha256",
    ):
        if not _valid_hash(report[field]):
            raise BridgeGateBlocked("qualification report contains an invalid digest")
    body = {key: value for key, value in report.items() if key != "manifest_sha256"}
    if report["manifest_sha256"] != canonical_hash(body):
        raise BridgeGateBlocked("qualification report digest is invalid")
    seen: set[tuple[str, str]] = set()
    families: dict[str, str] = {}
    artifact_paths: set[str] = set()
    for index, value in enumerate(report["executions"]):
        row = _exact(
            value,
            {
                "candidate_id",
                "family",
                "role",
                "request_sha256",
                "capsule_envelope_sha256",
                "oracle_envelope_sha256",
                "result_sha256",
                "artifact_path",
                "artifact_sha256",
            },
            f"qualification execution {index}",
        )
        key = (row["candidate_id"], row["role"])
        relative = _safe_path(row["artifact_path"], f"qualification execution {index} artifact")
        if (
            not isinstance(row["candidate_id"], str)
            or IDENTIFIER.fullmatch(row["candidate_id"]) is None
            or (row["family"], row["role"]) not in ROLE_FAMILIES
            or key in seen
            or row["artifact_path"] in artifact_paths
            or relative.as_posix() != row["artifact_path"]
            or not row["artifact_path"].startswith("artifacts/")
            or not row["artifact_path"].endswith(".json")
            or any(
                not _valid_hash(row[field])
                for field in (
                    "request_sha256",
                    "capsule_envelope_sha256",
                    "oracle_envelope_sha256",
                    "result_sha256",
                    "artifact_sha256",
                )
            )
        ):
            raise BridgeGateBlocked("qualification execution roster drifted")
        previous_family = families.setdefault(row["candidate_id"], row["family"])
        if previous_family != row["family"]:
            raise BridgeGateBlocked("qualification candidate family drifted")
        seen.add(key)
        artifact_paths.add(row["artifact_path"])
    if {(row["family"], row["role"]) for row in report["executions"]} != ROLE_FAMILIES or len(
        families
    ) != 3:
        raise BridgeGateBlocked("qualification semantic roster is not exact")
    return report


_CHILD_ROOT_LOCATOR_PATTERNS = {
    "production-process-root": re.compile(r"^\.w3-production-[0-9a-f]{24}$"),
    "production-runtime-root": re.compile(r"^\.w3-runtime-[0-9a-f]{24}$"),
    "production-trusted-root": re.compile(r"^\.w3-trusted-[0-9a-f]{24}$"),
}
_CHILD_PUBLICATION_LOCATOR_PATTERN = re.compile(r"^qualifications/[0-9a-f]{64}$")


def _remeasure_child_retained_roots(run_root: _AnchoredDirectory, cleanup_value: Any) -> None:
    cleanup = _validate_cleanup(
        cleanup_value,
        qualified=True,
        expected_kinds=(
            "production-process-root",
            "production-runtime-root",
            "production-trusted-root",
        ),
    )
    for index, root in enumerate(cleanup["retained_roots"]):
        locator = _safe_path(root["locator"], f"child retained root {index} locator")
        if (
            len(locator.parts) != 1
            or _CHILD_ROOT_LOCATOR_PATTERNS[root["kind"]].fullmatch(locator.as_posix()) is None
        ):
            raise BridgeGateBlocked("child retained root locator is outside its run namespace")
        handle: _AnchoredDirectory | None = None
        try:
            handle = _open_child_directory(
                run_root,
                locator.as_posix(),
                f"child retained root {index}",
                mode=0o555,
                create=False,
            )
            handle.assert_path_identity()
            witness_before = _holder_change_witness(handle.descriptor)
            snapshot_caps = (
                *RETAINED_ROOT_CAPS[root["kind"]],
                RETAINED_ROOT_FILE_CAPS[root["kind"]],
            )
            first, counts = _snapshot_holder_tree(
                handle.descriptor, kind=root["kind"], caps=snapshot_caps
            )
            witness_middle = _holder_change_witness(handle.descriptor)
            second, second_counts = _snapshot_holder_tree(
                handle.descriptor, kind=root["kind"], caps=snapshot_caps
            )
            witness_after = _holder_change_witness(handle.descriptor)
            digest = bytes_hash(first)
            if (
                first != second
                or counts != second_counts
                or len({witness_before, witness_middle, witness_after}) != 1
                or counts != root["counts"]
                or digest != root["physical_roster_sha256"]
                or digest != root["snapshot_first_sha256"]
                or digest != root["snapshot_second_sha256"]
            ):
                raise BridgeGateBlocked("child retained root remeasurement differs from report")
            handle.assert_path_identity()
        finally:
            if handle is not None:
                handle.close()


def _blocked_child_locator(root: dict[str, Any], index: int) -> PurePosixPath:
    locator = _safe_path(root["locator"], f"blocked child retained root {index} locator")
    kind = root["kind"]
    if kind in _CHILD_ROOT_LOCATOR_PATTERNS:
        if (
            len(locator.parts) != 1
            or _CHILD_ROOT_LOCATOR_PATTERNS[kind].fullmatch(locator.as_posix()) is None
        ):
            raise BridgeGateBlocked(
                "blocked child retained root locator is outside its run namespace"
            )
    elif kind == "qualification-publication-partial-root":
        if (
            len(locator.parts) != 2
            or _CHILD_PUBLICATION_LOCATOR_PATTERN.fullmatch(locator.as_posix()) is None
        ):
            raise BridgeGateBlocked(
                "blocked child publication locator is outside its artifact namespace"
            )
    else:
        raise BridgeGateBlocked("blocked child retained root kind is invalid")
    return locator


def _open_blocked_child_retained_root(
    *,
    artifact_root: _AnchoredDirectory,
    run_root: _AnchoredDirectory,
    root: dict[str, Any],
    locator: PurePosixPath,
    index: int,
) -> tuple[_AnchoredDirectory, _AnchoredDirectory | None]:
    if root["kind"] in _CHILD_ROOT_LOCATOR_PATTERNS:
        handle: _AnchoredDirectory | None = None
        try:
            handle = _open_child_directory(
                run_root,
                locator.as_posix(),
                f"blocked child retained root {index}",
                mode=0o555,
                create=False,
            )
            return handle, None
        except BaseException:
            if handle is not None:
                handle.close()
            raise
    namespace: _AnchoredDirectory | None = None
    handle = None
    try:
        namespace = _open_child_directory(
            artifact_root,
            "qualifications",
            "blocked child qualification namespace",
            mode=0o700,
            create=False,
        )
        handle = _open_child_directory(
            namespace,
            locator.parts[1],
            f"blocked child publication root {index}",
            mode=0o555,
            create=False,
        )
        return handle, namespace
    except BaseException:
        if handle is not None:
            handle.close()
        if namespace is not None:
            namespace.close()
        raise


def _remeasure_blocked_child_retained_roots(
    *,
    artifact_root: _AnchoredDirectory,
    run_root: _AnchoredDirectory,
    cleanup_value: Any,
) -> None:
    cleanup = _validate_cleanup(
        cleanup_value,
        qualified=False,
        blocked_prefixes=BLOCKED_CHILD_RETAINED_PREFIXES,
    )
    for index, root in enumerate(cleanup["retained_roots"]):
        locator = _blocked_child_locator(root, index)
        if root["state"] == "unmeasurable":
            continue
        handle: _AnchoredDirectory | None = None
        namespace: _AnchoredDirectory | None = None
        try:
            handle, namespace = _open_blocked_child_retained_root(
                artifact_root=artifact_root,
                run_root=run_root,
                root=root,
                locator=locator,
                index=index,
            )
            handle.assert_path_identity()
            witness_before = _holder_change_witness(handle.descriptor)
            snapshot_caps = (
                *RETAINED_ROOT_CAPS[root["kind"]],
                RETAINED_ROOT_FILE_CAPS[root["kind"]],
            )
            first, counts = _snapshot_holder_tree(
                handle.descriptor, kind=root["kind"], caps=snapshot_caps
            )
            witness_middle = _holder_change_witness(handle.descriptor)
            second, second_counts = _snapshot_holder_tree(
                handle.descriptor, kind=root["kind"], caps=snapshot_caps
            )
            witness_after = _holder_change_witness(handle.descriptor)
            digest = bytes_hash(first)
            if (
                first != second
                or counts != second_counts
                or len({witness_before, witness_middle, witness_after}) != 1
                or counts != root["counts"]
                or any(
                    root[field] != digest
                    for field in (
                        "physical_roster_sha256",
                        "normalized_roster_sha256",
                        "snapshot_first_sha256",
                        "snapshot_second_sha256",
                    )
                )
            ):
                raise BridgeGateBlocked(
                    "blocked child retained root remeasurement differs from report"
                )
            handle.assert_path_identity()
            if namespace is not None:
                namespace.assert_path_identity()
            artifact_root.assert_path_identity()
            run_root.assert_path_identity()
        finally:
            if handle is not None:
                handle.close()
            if namespace is not None:
                namespace.close()


def _runtime_authority(authority: dict[str, Any]) -> dict[str, Any]:
    capsule = authority["capsule"]
    tooling = capsule["tooling"]
    snapshot = f"snapshot://{PINNED_METIS_REVISION}/{PINNED_METIS_TREE}"
    runtime = {
        "node": PINNED_NODE_VERSION,
        "node_path": f"node://{PINNED_NODE_VERSION}",
        "loader_path": f"{snapshot}/.metis-oracle/native_ts_loader.mjs",
        "loader_sha256": capsule["loader"]["sha256"],
        "loader_flags": list(PINNED_LOADER_FLAGS),
        "runner_path": f"{snapshot}/.metis-oracle/runner.ts",
        "snapshot_revision": PINNED_METIS_REVISION,
        "snapshot_tree": PINNED_METIS_TREE,
        "tooling_package_sha256": tooling["package_sha256"],
        "tooling_lock_sha256": tooling["lock_sha256"],
        "node_modules_sha256": tooling["node_modules_sha256"],
        "node_binary_sha256": authority["runtime"]["node"]["sha256"],
        "sandbox_exec_path": "sandbox-exec:///usr/bin/sandbox-exec",
        "oracle_policy_version": "2",
        "oracle_policy_sha256": PINNED_ORACLE_POLICY_SHA256,
        "execution_policy_sha256": PINNED_CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"],
    }
    return {
        "toolchain": {
            "revision": PINNED_METIS_REVISION,
            "tree": PINNED_METIS_TREE,
            "language_version": "0.43",
        },
        "runtime_identity": runtime,
        "evidence_pins": {
            "runner_sha256": capsule["runner"]["sha256"],
            "loader_sha256": capsule["loader"]["sha256"],
            "tooling_package_sha256": tooling["package_sha256"],
            "tooling_lock_sha256": tooling["lock_sha256"],
            "node_modules_sha256": tooling["node_modules_sha256"],
            "node_binary_sha256": authority["runtime"]["node"]["sha256"],
            "oracle_policy_sha256": PINNED_ORACLE_POLICY_SHA256,
            "execution_policy_sha256": PINNED_CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"],
            "metis_status_sha256": canonical_hash(""),
        },
    }


def _validate_artifact(
    raw: bytes,
    row: dict[str, Any],
    authority: dict[str, Any],
) -> None:
    artifact = _decode_canonical(raw, "replay artifact")
    artifact = _exact(
        artifact,
        {
            "schema_version",
            "protocol",
            "execution_id",
            "request_sha256",
            "capsule_manifest_sha256",
            "execution_policy",
            "oracle_envelope",
            "manifest_sha256",
        },
        "replay artifact",
    )
    body = {key: item for key, item in artifact.items() if key != "manifest_sha256"}
    if (
        type(artifact["schema_version"]) is not int
        or artifact["schema_version"] != 3
        or artifact["protocol"] != "metis-runtime-capsule-v3"
        or artifact["execution_id"] != f"{row['candidate_id']}.{row['role']}"
        or artifact["request_sha256"] != row["request_sha256"]
        or artifact["capsule_manifest_sha256"] != authority["capsule"]["manifest_sha256"]
        or artifact["execution_policy"] != PINNED_CAPSULE_EXECUTION_POLICY
        or artifact["manifest_sha256"] != canonical_hash(body)
        or bytes_hash(raw) != row["artifact_sha256"]
        or canonical_hash(artifact) != row["capsule_envelope_sha256"]
    ):
        raise BridgeGateBlocked("replay artifact is not bound to its report and capsule")
    oracle = _exact(
        artifact["oracle_envelope"],
        {"schema_version", "result", "evidence"},
        "replay Oracle envelope",
    )
    if type(oracle["schema_version"]) is not int or oracle["schema_version"] != 1:
        raise BridgeGateBlocked("replay Oracle envelope schema drifted")
    result = _exact(
        oracle["result"],
        {
            "schema_version",
            "status",
            "endpoint",
            "diagnostics",
            "ast",
            "ir",
            "toolchain",
            "runtime",
            "failure",
        },
        "replay Oracle result",
    )
    evidence = _exact(
        oracle["evidence"],
        {
            "input_sha256",
            "diagnostics_sha256",
            "ast_sha256",
            "ir_sha256",
            "toolchain_revision",
            "toolchain_tree",
            "runtime_sha256",
            "runtime_identity",
            "runner_sha256",
            "loader_sha256",
            "tooling_package_sha256",
            "tooling_lock_sha256",
            "node_modules_sha256",
            "node_binary_sha256",
            "oracle_policy_sha256",
            "execution_policy_sha256",
            "metis_status_sha256",
            "metis_status",
            "envelope_sha256",
        },
        "replay Oracle evidence",
    )
    runtime = _runtime_authority(authority)
    ast_inventory = result["ast"].get("inventory") if isinstance(result["ast"], dict) else None
    ir_value = result["ir"].get("value") if isinstance(result["ir"], dict) else None
    expected_status = "invalid" if row["role"] == "mutated" else "ok"
    if (
        canonical_hash(oracle) != row["oracle_envelope_sha256"]
        or canonical_hash(result) != row["result_sha256"]
        or type(result["schema_version"]) is not int
        or result["schema_version"] != 1
        or result["status"] != expected_status
        or not isinstance(result["diagnostics"], list)
        or ast_inventory is None
        or result["toolchain"] != runtime["toolchain"]
        or result["runtime"] != runtime["runtime_identity"]
        or evidence["input_sha256"] != row["request_sha256"]
        or evidence["diagnostics_sha256"] != canonical_hash(result["diagnostics"])
        or evidence["ast_sha256"] != canonical_hash(ast_inventory)
        or evidence["ir_sha256"] != (None if ir_value is None else canonical_hash(ir_value))
        or evidence["toolchain_revision"] != PINNED_METIS_REVISION
        or evidence["toolchain_tree"] != PINNED_METIS_TREE
        or evidence["runtime_identity"] != runtime["runtime_identity"]
        or evidence["runtime_sha256"] != canonical_hash(runtime["runtime_identity"])
        or any(evidence[key] != value for key, value in runtime["evidence_pins"].items())
        or evidence["metis_status"] != ""
    ):
        raise BridgeGateBlocked("replay Oracle evidence is not authority-bound")
    without_envelope_sha = {
        **oracle,
        "evidence": {key: item for key, item in evidence.items() if key != "envelope_sha256"},
    }
    if evidence["envelope_sha256"] != canonical_hash(without_envelope_sha):
        raise BridgeGateBlocked("replay Oracle evidence digest is invalid")


def _kill_registered_groups(groups: set[int]) -> None:
    failures: list[OSError] = []
    for group in sorted(groups):
        try:
            if os.getpgid(group) != group or os.getsid(group) != group:
                continue
        except ProcessLookupError:
            continue
        except OSError as error:
            failures.append(error)
            continue
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            continue
        except OSError as error:
            failures.append(error)
    if failures:
        raise BridgeGateBlocked("registered child group cleanup failed") from failures[0]


def _kill_qualifier_group(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError):
        if os.getpgid(process.pid) == process.pid:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    try:
        process.wait(timeout=BRIDGE_CLEANUP_GRACE_SECONDS)
    except subprocess.TimeoutExpired as error:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        process.wait(timeout=BRIDGE_CLEANUP_GRACE_SECONDS)
        raise BridgeGateBlocked("fresh qualifier group could not be reaped") from error
    deadline = time.monotonic() + BRIDGE_CLEANUP_GRACE_SECONDS
    while True:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        if time.monotonic() >= deadline:
            raise BridgeGateBlocked("fresh qualifier descendants remained after group kill")
        time.sleep(0.01)


def _receive_child_registrations(
    control: socket.socket,
    *,
    nonce: str,
    expected_roles: frozenset[str] | None,
    registered: dict[str, int],
    errors: list[str],
    lock: threading.Lock,
) -> None:
    buffer = bytearray()
    try:
        while True:
            chunk = control.recv(BRIDGE_REGISTRATION_LIMIT + 1)
            if not chunk:
                if buffer:
                    raise BridgeGateBlocked("bridge child registration ended mid-record")
                return
            buffer.extend(chunk)
            if len(buffer) > BRIDGE_REGISTRATION_LIMIT:
                raise BridgeGateBlocked("bridge child registration exceeds its cap")
            while b"\n" in buffer:
                raw, _, remainder = buffer.partition(b"\n")
                buffer[:] = remainder
                try:
                    line = raw.decode("ascii")
                except UnicodeDecodeError as error:
                    raise BridgeGateBlocked("bridge child registration is not ASCII") from error
                fields = line.split(" ")
                if len(fields) != 6 or fields[0] != "REGISTER" or fields[1] != nonce:
                    raise BridgeGateBlocked("bridge child registration identity is invalid")
                role = fields[2]
                if BRIDGE_ROLE.fullmatch(role) is None or (
                    expected_roles is not None and role not in expected_roles
                ):
                    raise BridgeGateBlocked("bridge child registration role is invalid")
                numeric = fields[3:]
                if any(re.fullmatch(r"[1-9][0-9]{0,9}", field) is None for field in numeric):
                    raise BridgeGateBlocked("bridge child registration process identity is invalid")
                pid, pgid, sid = (int(field) for field in numeric)
                if pid != pgid or pid != sid:
                    raise BridgeGateBlocked("bridge child is not its session and group leader")
                try:
                    if os.getpgid(pid) != pid or os.getsid(pid) != pid:
                        raise BridgeGateBlocked("bridge child live process identity is invalid")
                except ProcessLookupError as error:
                    raise BridgeGateBlocked("bridge child vanished before registration") from error
                with lock:
                    if role in registered or pid in registered.values():
                        raise BridgeGateBlocked("bridge child registration is duplicated")
                    registered[role] = pid
                control.sendall(f"ACK {nonce} {pid}\n".encode("ascii"))
    except (BridgeGateBlocked, OSError) as error:
        with lock:
            errors.append(str(error))
        with contextlib.suppress(OSError):
            control.shutdown(socket.SHUT_RDWR)


def _registered_groups(registered: dict[str, int], lock: threading.Lock) -> set[int]:
    with lock:
        return set(registered.values())


def _assert_registered_groups_absent(groups: set[int]) -> None:
    deadline = time.monotonic() + BRIDGE_CLEANUP_GRACE_SECONDS
    first_cleanup_error: BridgeGateBlocked | None = None
    while True:
        residual: set[int] = set()
        for group in sorted(groups):
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                continue
            except OSError as error:
                residual.add(group)
                if first_cleanup_error is None:
                    first_cleanup_error = BridgeGateBlocked(
                        "registered child group presence check failed"
                    )
                    first_cleanup_error.__cause__ = error
            else:
                residual.add(group)
        if not residual:
            if first_cleanup_error is not None:
                raise first_cleanup_error
            return
        try:
            _kill_registered_groups(residual)
        except BridgeGateBlocked as error:
            if first_cleanup_error is None:
                first_cleanup_error = error
        if time.monotonic() >= deadline:
            if first_cleanup_error is not None:
                raise first_cleanup_error
            raise BridgeGateBlocked("fresh qualifier left a registered child group alive")
        time.sleep(0.01)


def _execute_qualifier_preimage(
    *,
    python: Path,
    qualifier: Path,
    qualifier_preimage: bytes,
    arguments: list[str],
    timeout: float,
    expected_child_roles: frozenset[str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    if (
        not qualifier_preimage
        or len(qualifier_preimage) > MAX_REPORT_BYTES
        or bytes_hash(qualifier_preimage) != PINNED_QUALIFIER_SHA256
    ):
        raise BridgeGateBlocked("fresh qualifier preimage differs from the bridge trust root")
    if type(timeout) not in {int, float} or timeout <= 0:
        raise BridgeGateBlocked("fresh qualifier timeout is invalid")
    control_nonce = secrets.token_hex(32)
    parent_control: socket.socket | None = None
    child_control: socket.socket | None = None
    registered: dict[str, int] = {}
    registration_errors: list[str] = []
    registration_lock: Any | None = None
    process: subprocess.Popen[bytes] | None = None
    supervision_complete = False
    receiver: threading.Thread | None = None
    stdout_stream: Any | None = None
    stderr_stream: Any | None = None
    try:
        parent_control, child_control = socket.socketpair()
        registration_lock = threading.Lock()
        stdout_stream = tempfile.TemporaryFile()  # noqa: SIM115 - closed in the finalizer
        stderr_stream = tempfile.TemporaryFile()  # noqa: SIM115 - closed in the finalizer
        command = [
            str(python),
            "-I",
            "-S",
            "-B",
            "-c",
            QUALIFIER_BOOTSTRAP,
            str(qualifier),
            str(child_control.fileno()),
            control_nonce,
            *arguments,
        ]
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=stdout_stream,
            stderr=stderr_stream,
            env={"PATH": "", "LANG": "C", "LC_ALL": "C"},
            pass_fds=(child_control.fileno(),),
            start_new_session=True,
        )
        child_control.close()
        if os.getpgid(process.pid) != process.pid or os.getsid(process.pid) != process.pid:
            _kill_qualifier_group(process)
            raise BridgeGateBlocked("fresh qualifier is not its session and group leader")
        receiver = threading.Thread(
            target=_receive_child_registrations,
            kwargs={
                "control": parent_control,
                "nonce": control_nonce,
                "expected_roles": expected_child_roles,
                "registered": registered,
                "errors": registration_errors,
                "lock": registration_lock,
            },
            name="w3-bridge-child-registry",
            daemon=True,
        )
        receiver.start()
        try:
            process.communicate(input=qualifier_preimage, timeout=float(timeout))
        except subprocess.TimeoutExpired as error:
            with contextlib.suppress(OSError):
                parent_control.shutdown(socket.SHUT_RDWR)
            groups = _registered_groups(registered, registration_lock)
            _kill_registered_groups(groups)
            try:
                process.communicate(timeout=BRIDGE_CLEANUP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                _kill_qualifier_group(process)
                process.communicate()
            _kill_registered_groups(groups)
            _assert_registered_groups_absent(groups)
            raise BridgeGateBlocked("fresh qualifier exceeded its supervised timeout") from error
        finally:
            with contextlib.suppress(OSError):
                parent_control.shutdown(socket.SHUT_RDWR)
        parent_control.close()
        receiver.join(timeout=BRIDGE_CLEANUP_GRACE_SECONDS)
        if receiver.is_alive():
            _kill_qualifier_group(process)
            raise BridgeGateBlocked("bridge child registration channel did not close")
        groups = _registered_groups(registered, registration_lock)
        if registration_errors:
            _kill_registered_groups(groups)
            raise BridgeGateBlocked(registration_errors[0])
        if expected_child_roles is not None and frozenset(registered) != expected_child_roles:
            _kill_registered_groups(groups)
            raise BridgeGateBlocked("fresh qualifier child registration roster is incomplete")
        _assert_registered_groups_absent(groups)
        _kill_qualifier_group(process)
        supervision_complete = True
        stdout_stream.seek(0)
        stderr_stream.seek(0)
        stdout = stdout_stream.read(MAX_REPORT_BYTES + 2)
        stderr = stderr_stream.read(MAX_STDERR_BYTES + 1)
        if len(stdout) > MAX_REPORT_BYTES + 1:
            raise BridgeGateBlocked("fresh qualifier stdout exceeds its cap")
        if len(stderr) > MAX_STDERR_BYTES:
            raise BridgeGateBlocked("fresh qualifier stderr exceeds its cap")
        return subprocess.CompletedProcess(
            command, process.returncode, stdout=stdout, stderr=stderr
        )
    except BridgeGateBlocked:
        raise
    except (OSError, subprocess.SubprocessError) as error:
        raise BridgeGateBlocked("fresh qualifier could not execute") from error
    finally:
        cleanup_error: BridgeGateBlocked | None = None
        if not supervision_complete:
            for control in (child_control, parent_control):
                if control is None:
                    continue
                with contextlib.suppress(OSError):
                    control.shutdown(socket.SHUT_RDWR)
                with contextlib.suppress(OSError):
                    control.close()
            groups = (
                {}
                if registration_lock is None
                else _registered_groups(registered, registration_lock)
            )
            try:
                _kill_registered_groups(groups)
            except BridgeGateBlocked as error:
                cleanup_error = error
            if process is not None:
                try:
                    _kill_qualifier_group(process)
                except BridgeGateBlocked as error:
                    if cleanup_error is None:
                        cleanup_error = error
                except OSError as error:
                    if cleanup_error is None:
                        cleanup_error = BridgeGateBlocked("fresh qualifier group cleanup failed")
                        cleanup_error.__cause__ = error
            if receiver is not None and receiver.is_alive():
                receiver.join(timeout=BRIDGE_CLEANUP_GRACE_SECONDS)
            if receiver is not None and receiver.is_alive() and cleanup_error is None:
                cleanup_error = BridgeGateBlocked(
                    "bridge child registration receiver could not be joined"
                )
            late_groups = (
                {}
                if registration_lock is None
                else _registered_groups(registered, registration_lock)
            )
            try:
                _assert_registered_groups_absent(late_groups)
            except BridgeGateBlocked as error:
                if cleanup_error is None:
                    cleanup_error = error
        for control in (child_control, parent_control):
            if control is None:
                continue
            with contextlib.suppress(OSError):
                control.close()
        if stdout_stream is not None:
            stdout_stream.close()
        if stderr_stream is not None:
            stderr_stream.close()
        if cleanup_error is not None:
            raise cleanup_error


def _run_once(
    *,
    python: Path,
    qualifier: Path,
    qualifier_preimage: bytes,
    authority: Path,
    authority_value: dict[str, Any],
    authority_sha256: str,
    source_bundle: Path,
    dependency_bundle: Path,
    capsule: Path,
    node: Path,
    artifact_root: _AnchoredDirectory,
    run_root: _AnchoredDirectory,
    nonce: str,
    timeout: float,
) -> tuple[bytes, dict[str, Any], dict[str, bytes]]:
    artifact_root.assert_path_identity()
    run_root.assert_path_identity()
    arguments = [
        "--mode",
        "production-capsule-v3",
        "--authority",
        str(authority),
        "--authority-sha256",
        authority_sha256,
        "--source-bundle-root",
        str(source_bundle),
        "--dependency-bundle-root",
        str(dependency_bundle),
        "--capsule-root",
        str(capsule),
        "--node-path",
        str(node),
        "--artifact-root",
        str(artifact_root.path),
        "--run-root",
        str(run_root.path),
        "--run-nonce",
        nonce,
        "--timeout-seconds",
        str(timeout),
    ]
    completed = _execute_qualifier_preimage(
        python=python,
        qualifier=qualifier,
        qualifier_preimage=qualifier_preimage,
        arguments=arguments,
        timeout=timeout * BRIDGE_CHILD_COUNT + BRIDGE_SUPERVISION_OVERHEAD_SECONDS,
        expected_child_roles=BRIDGE_CHILD_ROLES,
    )
    if len(completed.stderr) > MAX_STDERR_BYTES or completed.stderr:
        raise BridgeGateBlocked("fresh qualifier emitted unregistered stderr")
    if len(completed.stdout) > MAX_REPORT_BYTES + 1:
        raise BridgeGateBlocked("fresh qualifier stdout exceeds its cap")
    if not completed.stdout.endswith(b"\n"):
        raise BridgeGateBlocked("fresh qualifier stdout is not canonical JSON")
    report = _decode_canonical(completed.stdout[:-1], "fresh qualifier stdout")
    if completed.returncode != 0:
        blocked = _exact(
            report,
            {
                "schema_version",
                "qualification_id",
                "qualification_kind",
                "status",
                "claim",
                "reason",
                "native_evidence",
                "cleanup",
            },
            "blocked fresh qualification",
        )
        if (
            type(blocked["schema_version"]) is not int
            or blocked["schema_version"] != 3
            or blocked["qualification_id"] != QUALIFICATION_ID
            or blocked["qualification_kind"] != "production-capsule-v3"
            or blocked["status"] != "blocked"
            or blocked["claim"] != "no_qualification_claim"
            or blocked["native_evidence"] != NATIVE_EVIDENCE
            or not isinstance(blocked["reason"], str)
            or not blocked["reason"]
        ):
            raise BridgeGateBlocked("fresh qualifier blocked report is invalid")
        _remeasure_blocked_child_retained_roots(
            artifact_root=artifact_root,
            run_root=run_root,
            cleanup_value=blocked["cleanup"],
        )
        error = BridgeGateBlocked("fresh qualifier returned a blocked report")
        error.child_report_bytes = completed.stdout[:-1]
        error.child_cleanup = blocked["cleanup"]
        raise error
    report = _validate_qualification(report, authority_value, authority_sha256)
    _remeasure_child_retained_roots(run_root, report["cleanup"])
    artifact_root.assert_path_identity()
    run_root.assert_path_identity()
    expected = {row["artifact_path"] for row in report["executions"]}
    rows = {row["artifact_path"]: row for row in report["executions"]}
    for name in expected:
        if _safe_path(name, "replay artifact path").as_posix() != name:
            raise BridgeGateBlocked("fresh replay artifact path is not canonical")
    qualifications: _AnchoredDirectory | None = None
    publication: _AnchoredDirectory | None = None
    try:
        qualifications = _open_child_directory(
            artifact_root,
            "qualifications",
            "fresh qualification namespace",
            mode=0o700,
            create=False,
        )
        publication = _open_child_directory(
            qualifications,
            report["manifest_sha256"][7:],
            "fresh qualification publication",
            mode=0o555,
            create=False,
        )
        snapshot = _snapshot_publication_descriptor(
            publication.descriptor,
            expected | {"qualification.json"},
        )
        artifact_root.assert_path_identity()
        run_root.assert_path_identity()
        qualifications.assert_path_identity()
        publication.assert_path_identity()
        qualification_bytes = snapshot.pop("qualification.json")
        if qualification_bytes != completed.stdout[:-1]:
            raise BridgeGateBlocked("published qualification report differs from stdout")
        artifacts = snapshot
        for name, raw in artifacts.items():
            _validate_artifact(raw, rows[name], authority_value)
        if len(artifacts) != 5:
            raise BridgeGateBlocked("fresh qualification artifact roster is not exact")
        artifact_root.assert_path_identity()
        run_root.assert_path_identity()
        qualifications.assert_path_identity()
        publication.assert_path_identity()
        return completed.stdout[:-1], report, artifacts
    finally:
        if publication is not None:
            publication.close()
        if qualifications is not None:
            qualifications.close()


def _validate_replay_result(
    value: Any,
    *,
    authority_sha256: str,
    capsule_sha256: str,
) -> dict[str, Any]:
    report = _exact(value, QUALIFIED_REPLAY_REPORT_KEYS, "qualified replay report")
    if (
        type(report["schema_version"]) is not int
        or report["schema_version"] != SCHEMA_VERSION
        or report["replay_id"] != REPLAY_ID
        or report["status"] != "replay-qualified"
        or report["claim"] != CLAIM
        or report["authority_manifest_sha256"] != authority_sha256
        or report["capsule_manifest_sha256"] != capsule_sha256
        or report["nonce_model"] != NONCE_MODEL
        or report["native_evidence"] != NATIVE_EVIDENCE
        or report["non_claims"] != NON_CLAIMS
    ):
        raise BridgeGateBlocked("qualified replay report contract is invalid")
    for field in (
        "authority_manifest_sha256",
        "normalized_projection_sha256",
        "capsule_manifest_sha256",
        "manifest_sha256",
    ):
        if not _valid_hash(report[field]):
            raise BridgeGateBlocked("qualified replay report digest is invalid")
    _exact_count_map(
        report["counts"],
        {
            "fresh_processes": 2,
            "physical_invocations": 10,
            "semantic_identities": 5,
            "candidates": 3,
            "artifacts_per_run": 5,
            "gaps": 0,
        },
        "qualified replay counts",
    )
    _exact_count_map(report["roles"], ROLES, "qualified replay roles")
    runs = report["runs"]
    if not isinstance(runs, list) or len(runs) != 2:
        raise BridgeGateBlocked("qualified replay physical-run roster is invalid")
    physical_rosters: list[list[dict[str, Any]]] = []
    for index, value_run in enumerate(runs, start=1):
        run = _exact(
            value_run,
            {
                "run_index",
                "qualification_manifest_sha256",
                "report_bytes_sha256",
                "cleanup",
            },
            f"qualified replay physical run {index}",
        )
        if (
            type(run["run_index"]) is not int
            or run["run_index"] != index
            or not _valid_hash(run["qualification_manifest_sha256"])
            or not _valid_hash(run["report_bytes_sha256"])
        ):
            raise BridgeGateBlocked("qualified replay physical-run binding is invalid")
        cleanup = _validate_cleanup(
            run["cleanup"],
            qualified=True,
            expected_kinds=(
                "production-process-root",
                "production-runtime-root",
                "production-trusted-root",
            ),
        )
        physical_rosters.append(cleanup["retained_roots"])
    if any(
        left["root_id"] == right["root_id"] or left["locator"] == right["locator"]
        for left, right in zip(physical_rosters[0], physical_rosters[1], strict=True)
    ):
        raise BridgeGateBlocked("qualified replay copied a physical retained descriptor")
    artifacts = report["artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) != 5:
        raise BridgeGateBlocked("qualified replay artifact roster is invalid")
    observed_paths: list[str] = []
    for index, value_artifact in enumerate(artifacts):
        artifact = _exact(value_artifact, {"path", "sha256"}, f"replay artifact {index}")
        path = _safe_path(artifact["path"], f"replay artifact {index} path").as_posix()
        if (
            not path.startswith("artifacts/")
            or not path.endswith(".json")
            or not _valid_hash(artifact["sha256"])
        ):
            raise BridgeGateBlocked("qualified replay artifact binding is invalid")
        observed_paths.append(path)
    if observed_paths != sorted(set(observed_paths)):
        raise BridgeGateBlocked("qualified replay artifact order is invalid")
    cleanup = _validate_cleanup(
        report["cleanup"], qualified=True, expected_kinds=("replay-holder-root",)
    )
    body = {key: item for key, item in report.items() if key != "manifest_sha256"}
    if report["manifest_sha256"] != canonical_hash(body):
        raise BridgeGateBlocked("qualified replay manifest is invalid")
    return report


def run_replay_gate(
    *,
    qualifier_path: str | os.PathLike[str],
    qualifier_sha256: str,
    authority_path: str | os.PathLike[str],
    authority_sha256: str,
    source_bundle_root: str | os.PathLike[str],
    dependency_bundle_root: str | os.PathLike[str],
    capsule_root: str | os.PathLike[str],
    node_path: str | os.PathLike[str],
    artifact_root: str | os.PathLike[str],
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    _require_protected_execution_broker()
    if type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= 60:
        raise BridgeGateBlocked("replay timeout is outside its cap")
    resolved = {
        "qualifier": _strict_canonical_path(
            qualifier_path, "replay qualifier", must_exist=True, directory=False
        ),
        "authority": _strict_canonical_path(
            authority_path, "replay authority", must_exist=True, directory=False
        ),
        "source": _strict_canonical_path(
            source_bundle_root, "replay source bundle", must_exist=True, directory=True
        ),
        "dependency": _strict_canonical_path(
            dependency_bundle_root,
            "replay dependency bundle",
            must_exist=True,
            directory=True,
        ),
        "capsule": _strict_canonical_path(
            capsule_root, "replay capsule", must_exist=True, directory=True
        ),
        "node": _strict_canonical_path(
            node_path, "replay registered Node", must_exist=True, directory=False
        ),
    }
    qualifier_preimage = _read_regular(resolved["qualifier"], MAX_REPORT_BYTES, "qualifier")
    measured_qualifier_sha256 = bytes_hash(qualifier_preimage)
    if measured_qualifier_sha256 != qualifier_sha256 or qualifier_sha256 != PINNED_QUALIFIER_SHA256:
        raise BridgeGateBlocked("replay qualifier differs from the bridge trust root")
    python = Path(sys.executable).resolve(strict=True)
    if python.is_symlink():
        raise BridgeGateBlocked("bridge Python executable may not be a symlink")
    launcher = _measured_launcher(
        resolved["qualifier"],
        measured_qualifier_sha256,
        python,
    )
    authority_value = _load_authority(resolved["authority"], authority_sha256, launcher)
    artifact = _strict_canonical_path(
        artifact_root,
        "replay artifact root",
        must_exist=False,
        directory=True,
    )
    registry = _RetainedHolderRegistry()
    artifact_handle: _AnchoredDirectory | None = None
    holder: _AnchoredDirectory | None = None
    observed_runs: list[dict[str, Any]] = []
    try:
        artifact_handle = _open_or_create_secure_root(artifact, "replay artifact root")
        holder = _create_random_directory(
            artifact_handle,
            ".w3-replay-",
            "replay holder",
            registry=registry,
        )
        artifact_handle.assert_path_identity()
        holder.assert_path_identity()
        runs: list[tuple[bytes, dict[str, Any], dict[str, bytes]]] = []
        for index in (1, 2):
            run_artifacts: _AnchoredDirectory | None = None
            run_root: _AnchoredDirectory | None = None
            try:
                run_artifacts = _open_child_directory(
                    holder,
                    f"artifacts-{index}",
                    f"replay artifact root {index}",
                )
                run_root = _open_child_directory(
                    holder,
                    f"run-{index}",
                    f"replay run root {index}",
                )
                try:
                    run_result = _run_once(
                        python=python,
                        qualifier=resolved["qualifier"],
                        qualifier_preimage=qualifier_preimage,
                        authority=resolved["authority"],
                        authority_value=authority_value,
                        authority_sha256=authority_sha256,
                        source_bundle=resolved["source"],
                        dependency_bundle=resolved["dependency"],
                        capsule=resolved["capsule"],
                        node=resolved["node"],
                        artifact_root=run_artifacts,
                        run_root=run_root,
                        nonce=secrets.token_hex(32),
                        timeout=float(timeout_seconds),
                    )
                except BridgeGateBlocked as error:
                    child_bytes = getattr(error, "child_report_bytes", None)
                    child_cleanup = getattr(error, "child_cleanup", None)
                    observed_runs.append(
                        {
                            "run_index": index,
                            "status": "blocked" if child_bytes is not None else "no-report",
                            "qualification_manifest_sha256": None,
                            "report_bytes_sha256": (
                                bytes_hash(child_bytes) if child_bytes is not None else None
                            ),
                            "cleanup": child_cleanup,
                        }
                    )
                    raise
                canonical_report_bytes = canonical_json_bytes(run_result[1])
                if run_result[0] not in {
                    canonical_report_bytes,
                    canonical_report_bytes + b"\n",
                }:
                    raise BridgeGateBlocked("fresh physical report bytes are not canonical")
                _validate_qualification(run_result[1], authority_value, authority_sha256)
                runs.append(run_result)
                observed_runs.append(
                    {
                        "run_index": index,
                        "status": "qualified",
                        "qualification_manifest_sha256": run_result[1]["manifest_sha256"],
                        "report_bytes_sha256": bytes_hash(run_result[0]),
                        "cleanup": run_result[1]["cleanup"],
                    }
                )
                artifact_handle.assert_path_identity()
                holder.assert_path_identity()
                run_artifacts.assert_path_identity()
                run_root.assert_path_identity()
            finally:
                if run_root is not None:
                    run_root.close()
                if run_artifacts is not None:
                    run_artifacts.close()
        projections = [_normalized_qualification_projection(run[1]) for run in runs]
        if projections[0] != projections[1] or runs[0][2] != runs[1][2]:
            raise BridgeGateBlocked("normalized fresh reports or artifacts differ")
        first_roots = runs[0][1]["cleanup"]["retained_roots"]
        second_roots = runs[1][1]["cleanup"]["retained_roots"]
        if any(
            left["root_id"] == right["root_id"] or left["locator"] == right["locator"]
            for left, right in zip(first_roots, second_roots, strict=True)
        ):
            raise BridgeGateBlocked("fresh physical retained descriptors were copied")
        report = runs[0][1]
        artifact_digests = [
            {"path": name, "sha256": bytes_hash(raw)} for name, raw in sorted(runs[0][2].items())
        ]
        normalized_projection_sha256 = canonical_hash(projections[0])
        cleanup = registry.cleanup(qualified=True)
        _validate_cleanup(cleanup, qualified=True, expected_kinds=("replay-holder-root",))
        body = {
            "schema_version": SCHEMA_VERSION,
            "replay_id": REPLAY_ID,
            "status": "replay-qualified",
            "claim": CLAIM,
            "authority_manifest_sha256": authority_value["manifest_sha256"],
            "runs": [
                {
                    "run_index": index,
                    "qualification_manifest_sha256": run[1]["manifest_sha256"],
                    "report_bytes_sha256": bytes_hash(run[0]),
                    "cleanup": run[1]["cleanup"],
                }
                for index, run in enumerate(runs, start=1)
            ],
            "normalized_projection_sha256": normalized_projection_sha256,
            "capsule_manifest_sha256": report["capsule_manifest_sha256"],
            "counts": {
                "fresh_processes": 2,
                "physical_invocations": 10,
                "semantic_identities": 5,
                "candidates": 3,
                "artifacts_per_run": 5,
                "gaps": 0,
            },
            "roles": ROLES,
            "nonce_model": NONCE_MODEL,
            "artifacts": artifact_digests,
            "native_evidence": dict(NATIVE_EVIDENCE),
            "non_claims": list(NON_CLAIMS),
            "cleanup": cleanup,
        }
        result = {**body, "manifest_sha256": canonical_hash(body)}
        _validate_replay_result(
            result,
            authority_sha256=authority_value["manifest_sha256"],
            capsule_sha256=report["capsule_manifest_sha256"],
        )
        artifact_handle.assert_path_identity()
        holder.assert_path_identity()
        return result
    except Exception as error:
        cleanup = registry.cleanup(qualified=False)
        _validate_cleanup(
            cleanup,
            qualified=False,
            blocked_prefixes=BLOCKED_REPLAY_RETAINED_PREFIXES,
        )
        if isinstance(error, BridgeGateBlocked):
            error.cleanup = cleanup
            error.observed_runs = observed_runs
            raise
        raise BridgeGateBlocked(
            "replay failed after retained holder creation",
            cleanup=cleanup,
            observed_runs=observed_runs,
        ) from error
    finally:
        if holder is not None:
            holder.close()
        registry.close()
        if artifact_handle is not None:
            artifact_handle.close()


def _blocked(
    reason: str,
    cleanup: dict[str, Any] | None = None,
    observed_runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cleanup_value = _empty_cleanup() if cleanup is None else cleanup
    observed_value = [] if observed_runs is None else observed_runs
    _validate_cleanup(
        cleanup_value,
        qualified=False,
        blocked_prefixes=BLOCKED_REPLAY_RETAINED_PREFIXES,
    )
    _validate_observed_runs(observed_value)
    report = {
        "schema_version": SCHEMA_VERSION,
        "replay_id": REPLAY_ID,
        "status": "blocked",
        "claim": "no_replay_claim",
        "reason": reason,
        "observed_runs": observed_value,
        "native_evidence": dict(NATIVE_EVIDENCE),
        "cleanup": cleanup_value,
    }
    blocked = _exact(report, BLOCKED_REPLAY_REPORT_KEYS, "blocked replay report")
    if (
        type(blocked["schema_version"]) is not int
        or blocked["schema_version"] != SCHEMA_VERSION
        or blocked["replay_id"] != REPLAY_ID
        or blocked["status"] != "blocked"
        or blocked["claim"] != "no_replay_claim"
        or blocked["native_evidence"] != NATIVE_EVIDENCE
        or not isinstance(blocked["reason"], str)
        or not blocked["reason"]
    ):
        raise BridgeGateBlocked("blocked replay report contract is invalid")
    if len(cleanup_value["retained_roots"]) > 1 or any(
        root["kind"] != "replay-holder-root" for root in cleanup_value["retained_roots"]
    ):
        raise BridgeGateBlocked("blocked replay holder roster is invalid")
    return blocked


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise BridgeGateBlocked(f"invalid command line: {message}")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("--qualifier", required=True)
    parser.add_argument("--qualifier-sha256", required=True)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--authority-sha256", required=True)
    parser.add_argument("--source-bundle-root", required=True)
    parser.add_argument("--dependency-bundle-root", required=True)
    parser.add_argument("--capsule-root", required=True)
    parser.add_argument("--node-path", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    try:
        arguments = parser.parse_args(argv)
        report = run_replay_gate(
            qualifier_path=arguments.qualifier,
            qualifier_sha256=arguments.qualifier_sha256,
            authority_path=arguments.authority,
            authority_sha256=arguments.authority_sha256,
            source_bundle_root=arguments.source_bundle_root,
            dependency_bundle_root=arguments.dependency_bundle_root,
            capsule_root=arguments.capsule_root,
            node_path=arguments.node_path,
            artifact_root=arguments.artifact_root,
            timeout_seconds=arguments.timeout_seconds,
        )
    except (BridgeGateBlocked, OSError, RuntimeError) as error:
        cleanup = error.cleanup if isinstance(error, BridgeGateBlocked) else None
        observed_runs = error.observed_runs if isinstance(error, BridgeGateBlocked) else None
        sys.stdout.buffer.write(
            canonical_json_bytes(_blocked(str(error), cleanup, observed_runs)) + b"\n"
        )
        return 2
    sys.stdout.buffer.write(canonical_json_bytes(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
