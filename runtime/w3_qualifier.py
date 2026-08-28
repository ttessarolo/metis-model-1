#!/usr/bin/env python3
"""One-shot, clean-process verifier for the bounded W3 qualification gate.

The launcher is intentionally standalone and standard-library only.  It never
imports the Model 1 package.  An independently supplied authority digest pins
the exact authority manifest, which in turn pins every byte copied into a
content-addressed bundle.  The bundled worker is untrusted: this launcher
reconstructs requests, roles, counts, semantic truth and every reported hash.

This file does not contain a production worker and cannot ratify semantic
truth.  Until an independent reviewer supplies an authority manifest for an
audited worker and registry, qualification is blocked before child creation.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
PROTOCOL = "w3-clean-process-v1"
QUALIFICATION_ID = "w3-f1-f3-clean-process-qualification-v1"
CLAIM = "three_candidate_infrastructure_only_no_accuracy_claim"
V3_SCHEMA_VERSION = 3
V3_PROTOCOL = "w3-production-capsule-worker-v3"
V3_QUALIFICATION_ID = "w3-f1-f3-production-capsule-qualification-v3"
V3_CLAIM = "three_ratified_smoke_specs_production_capsule_only_no_accuracy_claim"
V3_AUTHORITY_ID = "w3-f1-f3-production-capsule-authority-v3"
V3_KIMI_REPORT_SHA256 = "sha256:a810598d9b62143f6172a4faa58f91879d4ac19f097cc19255a6ce43356fb83a"
V3_PROJECT_SHA = "5a5d817bb3df817fbd5d47b7bc4edd4517f8d9b7"
V3_CANDIDATE_MANIFEST_SHA256 = (
    "sha256:4ee3e735179194b838ec38b0c11f1f9a166d640fcfece1eee68b6f9b6dd63bc5"
)
V3_SEMANTIC_REGISTRY_SHA256 = (
    "sha256:9b9aa14836eb6924e61df0ab1e0a7b7224f9958b78056ae66fd27f59868cc7c3"
)
V3_DEPENDENCY_FILES = 144
V3_DEPENDENCY_BYTES = 1_799_002
V3_DEPENDENCY_ROSTER_SHA256 = "db649bc14ee947ff43a2e5dbd540585123a259bb771a087692b72a4c0d463f42"
V3_NODE_BINARY_SHA256 = "sha256:5d9d3872911e2340a43b707962e68143de8a4e8d54628845c0c4f2de1fb7cd5c"
V3_NODE_BINARY_BYTES = 112_915_776
V3_RUNNER_SHA256 = "sha256:772baa27e981f611681330bc463aef2ebe06b5f4a83ef2a0313ccf66b6dfef5d"
V3_LOADER_SHA256 = "sha256:45e3557ce7ee345e2bca7de603c2ef8bc21aa2adb3f305d3f1cf6ee445273fee"
V3_LOADER_FLAGS = ("--disable-warning=ExperimentalWarning", "--experimental-loader")
V3_NATIVE_TRACE_FD_ENV = "METIS_MODEL1_NATIVE_TRACE_FD"
V3_PYTHON = {
    "implementation": "CPython",
    "version": "3.13.3",
    "abi": "cp313-macosx_arm64",
    "machine": "arm64",
}
V3_NON_CLAIMS = [
    "executed_preimage_authority=false",
    "no_w1_15_of_15_claim",
    "no_f4_f5_f6_claim",
    "no_benchmark_v1_claim",
    "no_w5_claim",
    "no_semantic_accuracy_claim",
]
V3_NATIVE_EVIDENCE = {
    "path": "manifests/w3-native-loader-evidence.json",
    "manifest_sha256": "sha256:a84ec4511009102f1c2cc23604a4147606e34030809537d1528fd49032f331f6",
}
EXECUTED_PREIMAGE_AUTHORITY = False
REGISTERED_PROTECTED_EXECUTION_BROKER_SHA256: str | None = None
HASH_PREFIX = "sha256:"
MAX_AUTHORITY_BYTES = 1024 * 1024
MAX_BUNDLE_FILE_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_BYTES = 32 * 1024 * 1024
MAX_WORKER_INPUT_BYTES = 4 * 1024 * 1024
MAX_WORKER_STDOUT_BYTES = 8 * 1024 * 1024
MAX_WORKER_STDERR_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 1024 * 1024
MAX_PUBLISHED_BYTES = (5 * MAX_ARTIFACT_BYTES) + MAX_REPORT_BYTES
MAX_TIMEOUT_SECONDS = 60.0
GC_POLICY = "separately_ratified_quiescent_exclusive_v1"
ZERO_HASH = "sha256:" + ("0" * 64)
RETAINED_ROOT_CAPS = {
    "worker-process-root": (512, 512, 128 * 1024 * 1024, MAX_WORKER_STDOUT_BYTES),
    "production-process-root": (512, 512, 128 * 1024 * 1024, MAX_WORKER_STDOUT_BYTES),
    "production-runtime-root": (8, 8, 128 * 1024 * 1024, 128 * 1024 * 1024),
    "production-trusted-root": (4096, 4096, 1024 * 1024 * 1024, MAX_BUNDLE_FILE_BYTES),
    "qualification-publication-partial-root": (
        128,
        128,
        32 * 1024 * 1024,
        MAX_ARTIFACT_BYTES,
    ),
}
BLOCKED_V1_RETAINED_PREFIXES = (
    (),
    ("worker-process-root",),
    ("worker-process-root", "qualification-publication-partial-root"),
)
BLOCKED_V3_RETAINED_PREFIXES = (
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
QUALIFIED_V3_RETAINED_KINDS = (
    "production-process-root",
    "production-runtime-root",
    "production-trusted-root",
)
QUALIFIED_V1_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "qualification_id",
        "status",
        "claim",
        "authority_manifest_sha256",
        "bundle_sha256",
        "semantic_registry_sha256",
        "candidate_manifest_sha256",
        "worker_input_sha256",
        "worker_output_sha256",
        "launcher",
        "counts",
        "roles",
        "executions",
        "stops",
        "cleanup",
        "manifest_sha256",
    }
)
BLOCKED_V1_REPORT_KEYS = frozenset(
    {"schema_version", "qualification_id", "status", "claim", "reason", "cleanup"}
)
QUALIFIED_V3_REPORT_KEYS = frozenset(
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
BLOCKED_V3_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "qualification_id",
        "qualification_kind",
        "status",
        "claim",
        "reason",
        "native_evidence",
        "cleanup",
    }
)
PINNED_METIS_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
PINNED_METIS_TREE = "75473e26deff4084a0eb077a4c3e27d52dc07998"
PINNED_NODE_VERSION = "v22.22.3"
REQUIRED_LAUNCHER_FLAGS = ("-I", "-S", "-B")
SANDBOX_EXEC_PATH = Path("/usr/bin/sandbox-exec")
OUTER_SANDBOX_POLICY_TEMPLATE = """(version 1)
(deny default)
(deny network*)
(allow process-exec (literal (param "PYTHON_EXECUTABLE")))
(allow file-read*)
(deny file-read*
  (subpath "/Users")
  (subpath "/Volumes")
  (subpath "/Network")
  (subpath "/Applications")
  (subpath "/private/etc")
  (subpath "/private/tmp")
  (subpath "/private/var/folders")
  (subpath "/Library/Keychains")
  (subpath (param "SOURCE_ROOT"))
  (subpath (param "ARTIFACT_ROOT")))
(allow file-read*
  (subpath (param "PYTHON_ROOT"))
  (subpath (param "BUNDLE_ROOT"))
  (subpath (param "PROCESS_ROOT")))
(allow file-write* (subpath (param "PROCESS_ROOT")))
(allow sysctl-read)
(allow mach-lookup)
"""
OUTER_SANDBOX_POLICY_TEMPLATE_SHA256 = (
    HASH_PREFIX + hashlib.sha256(OUTER_SANDBOX_POLICY_TEMPLATE.encode("utf-8")).hexdigest()
)
V3_OUTER_SANDBOX_POLICY_TEMPLATE = """(version 1)
(deny default)
(deny network*)
(deny process-fork)
(allow process-exec (literal (param "PYTHON_EXECUTABLE")))
(allow file-read*
  (literal "/")
  (literal "/dev/null")
  (subpath "/System/Library")
  (subpath "/usr/lib")
  (subpath "/private/var/db/dyld")
  (subpath (param "PYTHON_ROOT"))
  (subpath (param "SOURCE_BUNDLE_ROOT"))
  (subpath (param "DEPENDENCY_BUNDLE_ROOT"))
  (subpath (param "PROCESS_ROOT")))
(deny file-write*
  (subpath (param "SOURCE_BUNDLE_ROOT"))
  (subpath (param "DEPENDENCY_BUNDLE_ROOT")))
(allow file-write* (subpath (param "PROCESS_ROOT")))
(allow sysctl-read)
(allow mach-lookup)
"""
V3_CAPSULE_ANCESTOR_SLOTS = 32
_V3_CAPSULE_ANCESTOR_POLICY = "\n".join(
    f'  (literal (param "CAPSULE_ANCESTOR_{index:02d}"))'
    for index in range(V3_CAPSULE_ANCESTOR_SLOTS)
)
_V3_RUNTIME_ANCESTOR_POLICY = "\n".join(
    f'  (literal (param "RUNTIME_ANCESTOR_{index:02d}"))'
    for index in range(V3_CAPSULE_ANCESTOR_SLOTS)
)
V3_NODE_SANDBOX_POLICY_TEMPLATE = (
    """(version 1)
(deny default)
(deny network*)
(deny process-fork)
(allow process-exec (literal (param "NODE_EXECUTABLE")))
(allow file-read*
  (literal "/dev/null")
  (subpath "/System/Library")
  (subpath "/usr/lib")
  (subpath "/private/var/db/dyld")
  (subpath (param "RUNTIME_ROOT"))
  (subpath (param "CAPSULE_ROOT"))
  (subpath (param "PROCESS_ROOT")))
"""
    + '(allow file-read-data (literal "/"))\n'
    + '(allow file-read-metadata\n  (literal "/")\n'
    + _V3_CAPSULE_ANCESTOR_POLICY
    + "\n"
    + _V3_RUNTIME_ANCESTOR_POLICY
    + "\n)\n"
    + """\
(deny file-write*
  (subpath (param "RUNTIME_ROOT"))
  (subpath (param "CAPSULE_ROOT")))
(allow file-write* (subpath (param "PROCESS_ROOT")))
(allow sysctl-read)
(allow mach-lookup)
"""
)
V3_NODE_SANDBOX_POLICY_TEMPLATE_SHA256 = (
    HASH_PREFIX + hashlib.sha256(V3_NODE_SANDBOX_POLICY_TEMPLATE.encode("utf-8")).hexdigest()
)
# The bridge's minimal stdin bootstrap is independently hashed into the v3
# launcher identity.  It executes the measured qualifier preimage rather than
# reopening a mutable path.  Keep this pin synchronized with the literal
# bootstrap in runtime/w3_bridge_gate.py.
V3_QUALIFIER_BOOTSTRAP_SHA256 = (
    "sha256:42af379e5dcfd1d1d59f53829181a010aa1b540d7a8ad86b5efe9738383090f4"
)
V3_OUTER_SANDBOX_POLICY_TEMPLATE_SHA256 = (
    HASH_PREFIX
    + hashlib.sha256(
        V3_OUTER_SANDBOX_POLICY_TEMPLATE.encode("utf-8")
        + b"\0"
        + V3_NODE_SANDBOX_POLICY_TEMPLATE.encode("utf-8")
    ).hexdigest()
)
CANDIDATE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SEMANTIC_FILENAME_PATTERN = re.compile(
    r"^(?:[A-Za-z0-9][A-Za-z0-9._-]*/)*"
    r"[A-Za-z0-9][A-Za-z0-9._-]*\.metis$"
)
ARTIFACT_PATH_PATTERN = re.compile(
    r"^artifacts/(?:[A-Za-z0-9][A-Za-z0-9._-]*/)*"
    r"[A-Za-z0-9][A-Za-z0-9._-]*\.json$"
)
QUALIFICATION_STOPS = [
    "no_production_worker_or_runner_execution",
    "stdlib_import_closure_not_materialized_or_content_addressed",
    "no_w1_slice_or_dataset_promotion",
    "no_f4_f5_f6_claim",
    "no_semantic_accuracy_claim",
]
V3_QUALIFICATION_STOPS = list(V3_NON_CLAIMS)

EXPECTED_ROLE_COUNTS = {
    "author": 1,
    "before": 1,
    "after": 1,
    "mutated": 1,
    "fixed": 1,
}
ROLE_CONTRACT = {
    "F-1": (("author", "target_source", "ok"),),
    "F-2": (("before", "before_source", "ok"), ("after", "after_source", "ok")),
    "F-3": (("mutated", "mutated_source", "invalid"), ("fixed", "fixed_source", "ok")),
}
REQUIRED_BUNDLE_KINDS = frozenset({"w3", "schema", "manifest", "runner", "worker"})
EVIDENCE_PIN_KEYS = frozenset(
    {
        "runner_sha256",
        "loader_sha256",
        "tooling_package_sha256",
        "tooling_lock_sha256",
        "node_modules_sha256",
        "node_binary_sha256",
        "oracle_policy_sha256",
        "execution_policy_sha256",
        "metis_status_sha256",
    }
)
RUNTIME_IDENTITY_KEYS = frozenset(
    {
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
)
LAUNCHER_IDENTITY_KEYS = frozenset(
    {
        "qualifier_path",
        "qualifier_sha256",
        "python_executable",
        "python_executable_sha256",
        "python_version",
        "required_flags",
        "sandbox_exec_path",
        "sandbox_exec_sha256",
        "sandbox_policy_template_sha256",
    }
)
V3_LAUNCHER_IDENTITY_KEYS = LAUNCHER_IDENTITY_KEYS | {"qualifier_bootstrap_sha256"}
V3_CAPSULE_EXECUTION_POLICY = {
    "sandbox_policy_sha256": V3_NODE_SANDBOX_POLICY_TEMPLATE_SHA256,
    "capsule_ancestor_slots": V3_CAPSULE_ANCESTOR_SLOTS,
    "runtime_ancestor_slots": V3_CAPSULE_ANCESTOR_SLOTS,
    "process_fork": "denied",
    "supervision": "node-session-group-leader",
    "loader_flags": list(V3_LOADER_FLAGS),
}
EVIDENCE_KEYS = frozenset(
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
    }
)
RESULT_KEYS = frozenset(
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
    }
)


class QualificationBlocked(ValueError):
    """The bounded qualification cannot produce an authoritative green."""

    def __init__(self, message: str, *, cleanup: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.cleanup = cleanup


def _v3_capsule_process_environment(process_root: Path) -> dict[str, str]:
    environment = {
        "PATH": "",
        "LANG": "C",
        "LC_ALL": "C",
        "TMPDIR": str(process_root),
    }
    if V3_NATIVE_TRACE_FD_ENV in environment:
        raise QualificationBlocked("production capsule environment enables reference tracing")
    return environment


def _require_protected_execution_broker() -> None:
    if REGISTERED_PROTECTED_EXECUTION_BROKER_SHA256 is None:
        raise QualificationBlocked(
            "production qualification requires a protected execution broker authority"
        )
    raise QualificationBlocked("protected execution broker transport is not implemented")


def canonical_json_bytes(value: Any) -> bytes:
    """Encode exact deterministic JSON and reject non-finite numbers."""

    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise QualificationBlocked(f"value is not canonical JSON: {error}") from error
    return rendered.encode("utf-8")


def canonical_hash(value: Any) -> str:
    return HASH_PREFIX + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return HASH_PREFIX + hashlib.sha256(value).hexdigest()


def _valid_hash(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith(HASH_PREFIX):
        return False
    digest = value[len(HASH_PREFIX) :]
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


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
        raise QualificationBlocked(f"{label} must be a lexical-canonical absolute path")
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
            raise QualificationBlocked(f"{label} ancestry is unavailable") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise QualificationBlocked(f"{label} ancestry contains a symlink")
    if must_exist and missing:
        raise QualificationBlocked(f"{label} is unavailable")
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as error:
        raise QualificationBlocked(f"{label} is unavailable") from error
    if resolved != candidate:
        raise QualificationBlocked(f"{label} is not lexical-canonical")
    if not missing and directory is True and not candidate.is_dir():
        raise QualificationBlocked(f"{label} is not a directory")
    if not missing and directory is False and not candidate.is_file():
        raise QualificationBlocked(f"{label} is not a file")
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
            raise QualificationBlocked(f"{label} does not have exact mode {mode:o}")
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
            raise QualificationBlocked(f"{self.label} descriptor is closed")
        metadata = os.fstat(self.descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != self.mode
            or (metadata.st_dev, metadata.st_ino) != self.identity
        ):
            raise QualificationBlocked(f"{self.label} opened identity changed")
        try:
            path_metadata = os.stat(self.path, follow_symlinks=False)
        except OSError as error:
            raise QualificationBlocked(f"{self.label} pathname was replaced") from error
        if (
            not stat.S_ISDIR(path_metadata.st_mode)
            or stat.S_IMODE(path_metadata.st_mode) != self.mode
            or (path_metadata.st_dev, path_metadata.st_ino) != self.identity
        ):
            raise QualificationBlocked(f"{self.label} pathname was replaced")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        with contextlib.suppress(OSError):
            os.close(self.descriptor)
        if self.owns_parent_descriptor:
            with contextlib.suppress(OSError):
                os.close(self.parent_descriptor)

    def __enter__(self) -> _AnchoredDirectory:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _validate_child_name(name: str, label: str) -> None:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise QualificationBlocked(f"{label} name is invalid")


def _open_or_create_secure_root(path: Path, label: str) -> _AnchoredDirectory:
    """Open/create one root leaf from an independently opened canonical parent."""

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
            raise QualificationBlocked(f"{label} parent changed while it was opened")
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
        if isinstance(error, QualificationBlocked):
            raise
        if isinstance(error, OSError):
            raise QualificationBlocked(f"{label} could not be opened securely") from error
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
    mode: int,
    create: bool,
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
        if isinstance(error, QualificationBlocked):
            raise
        if isinstance(error, OSError):
            raise QualificationBlocked(f"{label} could not be opened securely") from error
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
    registry: _RetainedRootRegistry | None = None,
    kind: str | None = None,
    logical_root: str | None = None,
    anchor: str | None = None,
) -> _AnchoredDirectory:
    for _ in range(128):
        name = f"{prefix}{secrets.token_hex(12)}"
        token: int | None = None
        handle: _AnchoredDirectory | None = None
        if registry is not None:
            if kind is None or logical_root is None or anchor is None:
                raise QualificationBlocked("retained random root identity is incomplete")
            token = registry.intent(
                kind=kind,
                logical_root=logical_root,
                anchor=anchor,
                locator=name,
            )
        try:
            handle = _open_child_directory(
                parent,
                name,
                label,
                mode=0o700,
                create=True,
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
                handle.retained_token = token
            return handle
        except QualificationBlocked as error:
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
    raise QualificationBlocked(f"{label} could not allocate a unique name")


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


def _retained_locator(value: str, label: str) -> str:
    path = _safe_relative_path(value, label)
    if any("\n" in part or "\r" in part or "\x00" in part for part in path.parts):
        raise QualificationBlocked(f"{label} is not canonical")
    return path.as_posix()


def _seal_retained_tree(descriptor: int, kind: str) -> None:
    max_files, max_directories, max_bytes, max_file_bytes = RETAINED_ROOT_CAPS[kind]
    counts = {"files": 0, "directories": 0, "bytes": 0}

    def visit(directory: int) -> None:
        counts["directories"] += 1
        if counts["directories"] > max_directories:
            raise QualificationBlocked(f"{kind} directory count exceeds its cap")
        try:
            names = sorted(os.listdir(directory), key=lambda item: item.encode("utf-8"))
        except (OSError, UnicodeEncodeError) as error:
            raise QualificationBlocked(f"{kind} roster cannot be enumerated") from error
        for name in names:
            _retained_locator(name, f"{kind} entry")
            try:
                before = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except OSError as error:
                raise QualificationBlocked(f"{kind} entry changed before seal") from error
            if stat.S_ISDIR(before.st_mode):
                flags = _DIRECTORY_OPEN_FLAGS
            elif stat.S_ISREG(before.st_mode):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
            else:
                raise QualificationBlocked(f"{kind} contains a non-regular entry")
            child = -1
            try:
                child = os.open(name, flags, dir_fd=directory)
                opened = os.fstat(child)
                if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                    raise QualificationBlocked(f"{kind} entry changed while opened")
                if stat.S_ISDIR(opened.st_mode):
                    visit(child)
                    os.fchmod(child, 0o555)
                else:
                    if opened.st_nlink != 1:
                        raise QualificationBlocked(f"{kind} contains a hard-linked file")
                    counts["files"] += 1
                    counts["bytes"] += opened.st_size
                    if (
                        counts["files"] > max_files
                        or counts["bytes"] > max_bytes
                        or opened.st_size > min(max_file_bytes, 256 * 1024 * 1024)
                    ):
                        raise QualificationBlocked(
                            f"{kind} file or aggregate count exceeds its cap"
                        )
                    os.fchmod(child, 0o555 if kind == "production-runtime-root" else 0o444)
                after = os.stat(name, dir_fd=directory, follow_symlinks=False)
                retained = os.fstat(child)
                if (after.st_dev, after.st_ino) != (retained.st_dev, retained.st_ino):
                    raise QualificationBlocked(f"{kind} entry changed while sealed")
            except OSError as error:
                raise QualificationBlocked(f"{kind} could not be sealed") from error
            finally:
                if child >= 0:
                    with contextlib.suppress(OSError):
                        os.close(child)

    visit(descriptor)
    try:
        os.fchmod(descriptor, 0o555)
    except OSError as error:
        raise QualificationBlocked(f"{kind} root could not be sealed") from error


def _snapshot_retained_tree(
    descriptor: int,
    kind: str,
) -> tuple[bytes, dict[str, int]]:
    max_files, max_directories, max_bytes, max_file_bytes = RETAINED_ROOT_CAPS[kind]
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
        metadata = os.fstat(directory)
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o555:
            raise QualificationBlocked(f"{kind} directory is not sealed")
        counts["directories"] += 1
        if counts["directories"] > max_directories:
            raise QualificationBlocked(f"{kind} directory count exceeds its cap")
        relative_name = "." if prefix is None else prefix.as_posix()
        directory_row = row(relative_name, "directory", 0o555, 0, hashlib.sha256(b"").hexdigest())
        rows.append(directory_row)
        try:
            names = sorted(os.listdir(directory), key=lambda item: item.encode("utf-8"))
        except (OSError, UnicodeEncodeError) as error:
            raise QualificationBlocked(f"{kind} roster cannot be enumerated") from error
        for name in names:
            relative = PurePosixPath(name) if prefix is None else prefix / name
            rendered = _retained_locator(relative.as_posix(), f"{kind} roster path")
            try:
                before = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except OSError as error:
                raise QualificationBlocked(f"{kind} entry changed before snapshot") from error
            if stat.S_ISDIR(before.st_mode):
                flags = _DIRECTORY_OPEN_FLAGS
            elif stat.S_ISREG(before.st_mode):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
            else:
                raise QualificationBlocked(f"{kind} contains a non-regular entry")
            child = -1
            try:
                child = os.open(name, flags, dir_fd=directory)
                opened = os.fstat(child)
                if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                    raise QualificationBlocked(f"{kind} entry changed while opened")
                if stat.S_ISDIR(opened.st_mode):
                    visit(child, relative)
                else:
                    expected_mode = 0o555 if kind == "production-runtime-root" else 0o444
                    if stat.S_IMODE(opened.st_mode) != expected_mode or opened.st_nlink != 1:
                        raise QualificationBlocked(
                            f"{kind} regular file is not singly linked and sealed"
                        )
                    if opened.st_size > min(max_file_bytes, 256 * 1024 * 1024):
                        raise QualificationBlocked(f"{kind} file exceeds its cap")
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
                        raise QualificationBlocked(f"{kind} file changed while snapshotted")
                    counts["files"] += 1
                    counts["bytes"] += len(raw)
                    if counts["files"] > max_files or counts["bytes"] > max_bytes:
                        raise QualificationBlocked(f"{kind} roster exceeds its cap")
                    digest = hashlib.sha256(raw).hexdigest()
                    physical = row(rendered, "regular", expected_mode, len(raw), digest)
                    rows.append(physical)
            except OSError as error:
                raise QualificationBlocked(f"{kind} could not be snapshotted") from error
            finally:
                if child >= 0:
                    with contextlib.suppress(OSError):
                        os.close(child)

    visit(descriptor, None)
    return b"".join(rows), counts


def _retained_tree_change_witness(descriptor: int, kind: str) -> str:
    rows: list[tuple[Any, ...]] = []

    def visit(directory: int, prefix: PurePosixPath | None) -> None:
        metadata = os.fstat(directory)
        rendered = "." if prefix is None else prefix.as_posix()
        rows.append((rendered, *_stat_identity(metadata)))
        try:
            names = sorted(os.listdir(directory), key=lambda item: item.encode("utf-8"))
        except (OSError, UnicodeEncodeError) as error:
            raise QualificationBlocked(f"{kind} change witness cannot enumerate") from error
        for name in names:
            relative = PurePosixPath(name) if prefix is None else prefix / name
            _retained_locator(relative.as_posix(), f"{kind} witness path")
            child = -1
            try:
                before = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if stat.S_ISDIR(before.st_mode):
                    child = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=directory)
                    opened = os.fstat(child)
                    if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                        raise QualificationBlocked(f"{kind} changed during witness")
                    visit(child, relative)
                elif stat.S_ISREG(before.st_mode):
                    rows.append((relative.as_posix(), *_stat_identity(before)))
                else:
                    raise QualificationBlocked(f"{kind} witness found a non-regular entry")
            except OSError as error:
                raise QualificationBlocked(f"{kind} change witness failed") from error
            finally:
                if child >= 0:
                    with contextlib.suppress(OSError):
                        os.close(child)

    visit(descriptor, None)
    return canonical_hash(rows)


def _sealed_retained_root(
    *,
    descriptor: int,
    handle: _AnchoredDirectory | None,
    kind: str,
    logical_root: str,
    anchor: str,
    locator: str,
) -> dict[str, Any]:
    if kind not in RETAINED_ROOT_CAPS:
        raise QualificationBlocked("retained root kind is invalid")
    locator = _retained_locator(locator, "retained root locator")
    _seal_retained_tree(descriptor, kind)
    if handle is not None:
        handle.mode = 0o555
    witness_before = _retained_tree_change_witness(descriptor, kind)
    first, counts = _snapshot_retained_tree(descriptor, kind)
    witness_middle = _retained_tree_change_witness(descriptor, kind)
    second, second_counts = _snapshot_retained_tree(descriptor, kind)
    witness_after = _retained_tree_change_witness(descriptor, kind)
    if (
        first != second
        or counts != second_counts
        or len({witness_before, witness_middle, witness_after}) != 1
    ):
        raise QualificationBlocked(f"{kind} changed between retained snapshots")
    body = {
        "state": "sealed",
        "kind": kind,
        "logical_root": logical_root,
        "anchor": anchor,
        "locator": locator,
        "counts": counts,
        "physical_roster_sha256": _bytes_hash(first),
        "normalized_roster_sha256": _bytes_hash(first),
        "snapshot_first_sha256": _bytes_hash(first),
        "snapshot_second_sha256": _bytes_hash(second),
        "sealed": True,
    }
    return {**body, "root_id": canonical_hash(body)}


class _RetainedRootRegistry:
    """Retain descriptor identities and emit bounded point-in-time evidence."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []

    def intent(self, *, kind: str, logical_root: str, anchor: str, locator: str) -> int:
        if kind not in RETAINED_ROOT_CAPS:
            raise QualificationBlocked("retained root intent kind is invalid")
        locator = _retained_locator(locator, "retained root intent locator")
        self._entries.append(
            {
                "kind": kind,
                "logical_root": logical_root,
                "anchor": anchor,
                "locator": locator,
                "active": True,
                "creation_observed": False,
                "descriptor_observed": False,
                "descriptor": -1,
                "handle": None,
            }
        )
        return len(self._entries) - 1

    def cancel(self, token: int) -> None:
        entry = self._entries[token]
        if entry["creation_observed"]:
            raise QualificationBlocked("observed retained root intent cannot be cancelled")
        entry["active"] = False

    def mark_created(self, token: int) -> None:
        entry = self._entries[token]
        if entry["creation_observed"]:
            raise QualificationBlocked("retained root creation was observed twice")
        entry["creation_observed"] = True

    def was_created(self, token: int) -> bool:
        return bool(self._entries[token]["creation_observed"])

    def observe(self, token: int, handle: _AnchoredDirectory) -> None:
        entry = self._entries[token]
        if not entry["creation_observed"] or entry["descriptor_observed"]:
            raise QualificationBlocked("retained root intent was observed twice")
        descriptor = -1
        try:
            descriptor = os.dup(handle.descriptor)
            entry["descriptor"] = descriptor
            entry["descriptor_observed"] = True
            entry["handle"] = handle
        except BaseException as error:
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
            dict.__setitem__(entry, "descriptor", -1)
            dict.__setitem__(entry, "descriptor_observed", False)
            dict.__setitem__(entry, "handle", None)
            if isinstance(error, OSError):
                raise QualificationBlocked(
                    "retained root descriptor could not be retained"
                ) from error
            raise

    def complete(self, token: int) -> None:
        entry = self._entries[token]
        descriptor = entry["descriptor"]
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        entry["descriptor"] = -1
        entry["active"] = False
        entry["handle"] = None

    def cleanup(self, *, qualified: bool) -> dict[str, Any]:
        roots: list[dict[str, Any]] = []
        for entry in self._entries:
            if not entry["active"]:
                continue
            if not entry["creation_observed"]:
                continue
            if not entry["descriptor_observed"]:
                if qualified:
                    raise QualificationBlocked(
                        f"{entry['kind']} creation did not yield a retained descriptor"
                    )
                body = {
                    "state": "unmeasurable",
                    "kind": entry["kind"],
                    "logical_root": entry["logical_root"],
                    "anchor": entry["anchor"],
                    "locator": entry["locator"],
                    "creation_observed": True,
                    "reason": "creation attempt did not yield a retained descriptor",
                }
                roots.append({**body, "root_id": canonical_hash(body)})
                continue
            try:
                roots.append(
                    _sealed_retained_root(
                        descriptor=entry["descriptor"],
                        handle=entry["handle"],
                        kind=entry["kind"],
                        logical_root=entry["logical_root"],
                        anchor=entry["anchor"],
                        locator=entry["locator"],
                    )
                )
            except Exception as error:
                if qualified:
                    raise QualificationBlocked(
                        f"{entry['kind']} could not be sealed and measured"
                    ) from error
                body = {
                    "state": "unmeasurable",
                    "kind": entry["kind"],
                    "logical_root": entry["logical_root"],
                    "anchor": entry["anchor"],
                    "locator": entry["locator"],
                    "creation_observed": True,
                    "reason": str(error)[:512] or "retained root measurement failed",
                }
                roots.append({**body, "root_id": canonical_hash(body)})
        return {
            "status": "cleanup_deferred",
            "gc_policy": GC_POLICY,
            "delete_attempts": 0,
            "retained_roots": roots,
        }

    def close(self) -> None:
        for entry in self._entries:
            descriptor = entry["descriptor"]
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
                entry["descriptor"] = -1


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


_RETAINED_ROOT_IDENTITIES = {
    "worker-process-root": ("process", "artifact-root"),
    "production-process-root": ("process", "run-root"),
    "production-runtime-root": ("runtime", "run-root"),
    "production-trusted-root": ("trusted", "run-root"),
    "qualification-publication-partial-root": (
        "qualification-publication-partial",
        "artifact-root",
    ),
}


def _validate_cleanup(
    value: Any,
    *,
    qualified: bool,
    expected_kinds: tuple[str, ...] | None = None,
    blocked_prefixes: tuple[tuple[str, ...], ...] | None = None,
) -> dict[str, Any]:
    cleanup = _exact_keys(
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
        raise QualificationBlocked("retained cleanup contract is invalid")
    roots = cleanup["retained_roots"]
    observed_kinds = tuple(root.get("kind") if isinstance(root, dict) else None for root in roots)
    if qualified and expected_kinds is not None and observed_kinds != expected_kinds:
        raise QualificationBlocked("qualified retained root order is invalid")
    if not qualified and blocked_prefixes is not None and observed_kinds not in blocked_prefixes:
        raise QualificationBlocked("blocked retained root order is invalid")
    seen_ids: set[str] = set()
    seen_logical: set[tuple[str, str]] = set()
    for index, root_value in enumerate(roots):
        if not isinstance(root_value, dict):
            raise QualificationBlocked("retained root descriptor is invalid")
        state = root_value.get("state")
        if state == "sealed":
            root = _exact_keys(
                root_value,
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
            if root["sealed"] is not True:
                raise QualificationBlocked("sealed retained root boolean is invalid")
            counts = _exact_keys(
                root["counts"], {"files", "directories", "bytes"}, "retained root counts"
            )
            if any(type(counts[name]) is not int or counts[name] < 0 for name in counts):
                raise QualificationBlocked("retained root counts are invalid")
            kind = root["kind"]
            if kind not in RETAINED_ROOT_CAPS:
                raise QualificationBlocked("retained root kind is invalid")
            max_files, max_directories, max_bytes, _ = RETAINED_ROOT_CAPS[kind]
            if (
                counts["files"] > max_files
                or counts["directories"] < 1
                or counts["directories"] > max_directories
                or counts["bytes"] > max_bytes
            ):
                raise QualificationBlocked("retained root counts exceed their cap")
            if any(
                not _valid_hash(root[name])
                for name in (
                    "physical_roster_sha256",
                    "normalized_roster_sha256",
                    "snapshot_first_sha256",
                    "snapshot_second_sha256",
                    "root_id",
                )
            ) or not (
                root["physical_roster_sha256"]
                == root["normalized_roster_sha256"]
                == root["snapshot_first_sha256"]
                == root["snapshot_second_sha256"]
            ):
                raise QualificationBlocked("retained root digest is invalid")
        elif state == "unmeasurable" and not qualified:
            root = _exact_keys(
                root_value,
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
                raise QualificationBlocked("unmeasurable retained root is invalid")
            kind = root["kind"]
        else:
            raise QualificationBlocked("retained root state is invalid")
        if kind not in _RETAINED_ROOT_IDENTITIES:
            raise QualificationBlocked("retained root identity is invalid")
        logical_root, anchor = _RETAINED_ROOT_IDENTITIES[kind]
        if root["logical_root"] != logical_root or root["anchor"] != anchor:
            raise QualificationBlocked("retained root kind binding is invalid")
        _retained_locator(root["locator"], "retained root locator")
        body = {key: item for key, item in root.items() if key != "root_id"}
        if root["root_id"] != canonical_hash(body):
            raise QualificationBlocked("retained root id is invalid")
        logical_key = (kind, root["logical_root"])
        if root["root_id"] in seen_ids or logical_key in seen_logical:
            raise QualificationBlocked("retained root descriptor is duplicated")
        seen_ids.add(root["root_id"])
        seen_logical.add(logical_key)
    return cleanup


def _entry_exists_at(parent: _AnchoredDirectory, name: str) -> bool:
    _validate_child_name(name, "anchored entry")
    try:
        os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise QualificationBlocked("anchored entry could not be inspected") from error
    return True


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
        if not stat.S_ISREG(before.st_mode):
            raise QualificationBlocked(f"{label} identity is invalid")
        if stat.S_IMODE(before.st_mode) != mode:
            raise QualificationBlocked(f"{label} file mode changed")
        if before.st_size > limit:
            raise QualificationBlocked(f"{label} exceeds its size cap")
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
            raise QualificationBlocked(f"{label} changed while it was read")
        return raw
    except QualificationBlocked:
        raise
    except OSError as error:
        raise QualificationBlocked(f"{label} could not be read securely") from error
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _canonicalize_owned_regular_at(
    parent: _AnchoredDirectory,
    name: str,
    expected_bytes: bytes,
    canonical_bytes: bytes,
) -> None:
    """Rewrite only the retained inode and prove its canonical path identity stayed stable."""

    _validate_child_name(name, "owned canonicalization target")
    if (
        not isinstance(expected_bytes, bytes)
        or not isinstance(canonical_bytes, bytes)
        or len(expected_bytes) > MAX_WORKER_STDOUT_BYTES
        or len(canonical_bytes) > MAX_WORKER_STDOUT_BYTES
    ):
        raise QualificationBlocked("owned canonicalization bytes exceed their cap")
    descriptor = -1
    try:
        parent.assert_path_identity()
        before_path = os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
        descriptor = os.open(
            name,
            os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent.descriptor,
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_nlink != 1
            or (before_path.st_dev, before_path.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise QualificationBlocked("owned canonicalization target identity is invalid")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if b"".join(chunks) != expected_bytes or opened.st_size != len(expected_bytes):
            raise QualificationBlocked("owned canonicalization preimage changed")
        before_write_path = os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
        before_write_fd = os.fstat(descriptor)
        if _stat_identity(opened) != _stat_identity(before_write_fd) or (
            before_write_path.st_dev,
            before_write_path.st_ino,
        ) != (opened.st_dev, opened.st_ino):
            raise QualificationBlocked("owned canonicalization target changed before write")
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        pending = memoryview(canonical_bytes)
        while pending:
            written = os.write(descriptor, pending)
            if written <= 0:
                raise QualificationBlocked("owned canonicalization write was incomplete")
            pending = pending[written:]
        os.fsync(descriptor)
        after_fd = os.fstat(descriptor)
        after_path = os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
        parent.assert_path_identity()
        if (
            (after_fd.st_dev, after_fd.st_ino) != (opened.st_dev, opened.st_ino)
            or (after_path.st_dev, after_path.st_ino) != (opened.st_dev, opened.st_ino)
            or not stat.S_ISREG(after_fd.st_mode)
            or stat.S_IMODE(after_fd.st_mode) != 0o600
            or after_fd.st_nlink != 1
            or after_fd.st_size != len(canonical_bytes)
        ):
            raise QualificationBlocked("owned canonicalization target changed after write")
        os.lseek(descriptor, 0, os.SEEK_SET)
        rendered = bytearray()
        while len(rendered) < len(canonical_bytes):
            chunk = os.read(descriptor, min(64 * 1024, len(canonical_bytes) - len(rendered)))
            if not chunk:
                break
            rendered.extend(chunk)
        if bytes(rendered) != canonical_bytes:
            raise QualificationBlocked("owned canonicalization postimage changed")
    except QualificationBlocked:
        raise
    except OSError as error:
        raise QualificationBlocked("owned canonicalization failed securely") from error
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _snapshot_qualification_descriptor(
    root_descriptor: int,
    expected_files: set[str],
    *,
    immutable: bool,
) -> dict[str, bytes]:
    directory_mode = 0o555 if immutable else 0o700
    file_mode = 0o444 if immutable else 0o600
    root_metadata = os.fstat(root_descriptor)
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_IMODE(root_metadata.st_mode) != directory_mode
    ):
        raise QualificationBlocked("qualification tree root mode changed")
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    snapshot: dict[str, bytes] = {}
    total = 0

    def visit(descriptor: int, prefix: PurePosixPath | None = None) -> None:
        nonlocal total
        for name in sorted(os.listdir(descriptor)):
            _validate_child_name(name, "qualification tree entry")
            relative = PurePosixPath(name) if prefix is None else prefix / name
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise QualificationBlocked("qualification tree contains a symlink")
            if stat.S_ISDIR(metadata.st_mode):
                if stat.S_IMODE(metadata.st_mode) != directory_mode:
                    raise QualificationBlocked("qualification directory mode changed")
                actual_directories.add(relative.as_posix())
                child = -1
                try:
                    child = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
                    visit(child, relative)
                finally:
                    if child >= 0:
                        os.close(child)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise QualificationBlocked("qualification tree roster changed")
            relative_name = relative.as_posix()
            actual_files.add(relative_name)
            limit = (
                MAX_REPORT_BYTES if relative_name == "qualification.json" else MAX_ARTIFACT_BYTES
            )
            raw = _read_regular_at(
                descriptor,
                name,
                limit,
                f"qualification file {relative_name}",
                mode=file_mode,
            )
            total += len(raw)
            if total > MAX_PUBLISHED_BYTES:
                raise QualificationBlocked("qualification tree exceeds its aggregate size cap")
            snapshot[relative_name] = raw

    visit(root_descriptor)
    if actual_files != expected_files or actual_directories != _expected_tree_directories(
        expected_files
    ):
        raise QualificationBlocked("qualification tree roster changed")
    return snapshot


def _write_regular_relative(
    root_descriptor: int,
    relative: PurePosixPath,
    raw: bytes,
    label: str,
    *,
    mode: int = 0o600,
) -> None:
    descriptor = -1
    output = -1
    try:
        descriptor = os.dup(root_descriptor)
        for part in relative.parts[:-1]:
            with contextlib.suppress(FileExistsError):
                os.mkdir(part, 0o700, dir_fd=descriptor)
            child = -1
            try:
                child = os.open(part, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
                metadata = os.fstat(child)
                if stat.S_IMODE(metadata.st_mode) != 0o700:
                    raise QualificationBlocked(f"{label} directory mode is invalid")
                os.close(descriptor)
                descriptor, child = child, -1
            finally:
                if child >= 0:
                    with contextlib.suppress(OSError):
                        os.close(child)
        output = os.open(
            relative.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            mode,
            dir_fd=descriptor,
        )
        view = memoryview(raw)
        while view:
            written = os.write(output, view)
            if written <= 0:
                raise QualificationBlocked(f"{label} could not be written completely")
            view = view[written:]
        os.fchmod(output, mode)
        metadata = os.fstat(output)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != mode
            or metadata.st_size != len(raw)
        ):
            raise QualificationBlocked(f"{label} materialized with an invalid identity")
    except QualificationBlocked:
        raise
    except OSError as error:
        raise QualificationBlocked(f"{label} could not be materialized securely") from error
    finally:
        if output >= 0:
            with contextlib.suppress(OSError):
                os.close(output)
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _open_relative_parent_descriptor(
    root_descriptor: int,
    relative: PurePosixPath,
    label: str,
) -> int:
    descriptor = -1
    try:
        descriptor = os.dup(root_descriptor)
        for part in relative.parts[:-1]:
            child = -1
            try:
                child = os.open(part, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
                metadata = os.fstat(child)
                if stat.S_IMODE(metadata.st_mode) != 0o700:
                    raise QualificationBlocked(f"{label} directory mode is invalid")
                os.close(descriptor)
                descriptor, child = child, -1
            finally:
                if child >= 0:
                    with contextlib.suppress(OSError):
                        os.close(child)
        return descriptor
    except BaseException as error:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if isinstance(error, QualificationBlocked):
            raise
        if isinstance(error, OSError):
            raise QualificationBlocked(f"{label} ancestry could not be opened securely") from error
        raise


def _read_regular_relative(
    root_descriptor: int,
    relative: PurePosixPath,
    limit: int,
    label: str,
) -> bytes:
    parent = -1
    try:
        parent = _open_relative_parent_descriptor(root_descriptor, relative, label)
        metadata = os.stat(relative.name, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISLNK(metadata.st_mode):
            raise QualificationBlocked(f"{label} may not be a symlink")
        return _read_regular_at(
            parent,
            relative.name,
            limit,
            label,
            mode=0o600,
        )
    except QualificationBlocked:
        raise
    except OSError as error:
        raise QualificationBlocked(f"{label} could not be inspected securely") from error
    finally:
        if parent >= 0:
            os.close(parent)


def _replace_regular_relative(
    root_descriptor: int,
    relative: PurePosixPath,
    raw: bytes,
    label: str,
) -> None:
    parent = -1
    descriptor = -1
    try:
        parent = _open_relative_parent_descriptor(root_descriptor, relative, label)
        descriptor = os.open(
            relative.name,
            os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise QualificationBlocked(f"{label} identity is invalid")
        os.ftruncate(descriptor, 0)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise QualificationBlocked(f"{label} could not be written completely")
            view = view[written:]
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or stat.S_IMODE(after.st_mode) != 0o600
            or after.st_size != len(raw)
        ):
            raise QualificationBlocked(f"{label} changed while it was replaced")
    except QualificationBlocked:
        raise
    except OSError as error:
        raise QualificationBlocked(f"{label} could not be replaced securely") from error
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if parent >= 0:
            os.close(parent)


def _seal_directory_descriptor(descriptor: int) -> None:
    for name in os.listdir(descriptor):
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            child = -1
            try:
                child = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
                _seal_directory_descriptor(child)
            finally:
                if child >= 0:
                    os.close(child)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise QualificationBlocked("qualification tree contains an invalid entry")
        child = -1
        try:
            child = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
            os.fchmod(child, 0o444)
        finally:
            if child >= 0:
                os.close(child)
    os.fchmod(descriptor, 0o555)


def _seal_directory_ancestry_descriptor(descriptor: int) -> None:
    """Seal directories while preserving authority-bound executable file modes."""

    for name in os.listdir(descriptor):
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            child = -1
            try:
                child = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
                _seal_directory_ancestry_descriptor(child)
            finally:
                if child >= 0:
                    os.close(child)
        elif not stat.S_ISREG(metadata.st_mode):
            raise QualificationBlocked("preimage tree contains an invalid entry")
    os.fchmod(descriptor, 0o555)


def _exact_int(value: Any, expected: int, label: str) -> None:
    if type(value) is not int or value != expected:
        raise QualificationBlocked(f"{label} must be the exact integer {expected}")


def _require_launcher_flags() -> None:
    if not (
        sys.flags.isolated == 1 and sys.flags.no_site == 1 and sys.flags.dont_write_bytecode == 1
    ):
        raise QualificationBlocked("launcher requires exact isolated flags -I -S -B")


def _launcher_identity_from_preimage(qualifier: Path, qualifier_bytes: bytes) -> dict[str, Any]:
    try:
        python = Path(sys.executable).resolve(strict=True)
        sandbox = SANDBOX_EXEC_PATH.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise QualificationBlocked("launcher executable identity is unavailable") from error
    if qualifier.is_symlink() or python.is_symlink() or sandbox.is_symlink():
        raise QualificationBlocked("launcher executable identity may not be a symlink")
    python_bytes = _read_regular_file(python, MAX_BUNDLE_FILE_BYTES, "Python executable")
    sandbox_bytes = _read_regular_file(sandbox, MAX_BUNDLE_FILE_BYTES, "sandbox-exec")
    version = sys.version_info
    python_version = f"{version.major}.{version.minor}.{version.micro}"
    return {
        "qualifier_path": str(qualifier),
        "qualifier_sha256": _bytes_hash(qualifier_bytes),
        "python_executable": str(python),
        "python_executable_sha256": _bytes_hash(python_bytes),
        "python_version": python_version,
        "required_flags": list(REQUIRED_LAUNCHER_FLAGS),
        "sandbox_exec_path": str(sandbox),
        "sandbox_exec_sha256": _bytes_hash(sandbox_bytes),
        "sandbox_policy_template_sha256": OUTER_SANDBOX_POLICY_TEMPLATE_SHA256,
    }


def _launcher_identity() -> dict[str, Any]:
    try:
        qualifier = _strict_canonical_path(
            Path(__file__).resolve(strict=True),
            "qualifier",
            must_exist=True,
            directory=False,
        )
    except (OSError, RuntimeError) as error:
        raise QualificationBlocked("launcher executable identity is unavailable") from error
    qualifier_bytes = _read_regular_file(qualifier, MAX_BUNDLE_FILE_BYTES, "qualifier")
    return _launcher_identity_from_preimage(qualifier, qualifier_bytes)


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationBlocked(f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise QualificationBlocked(f"JSON contains non-finite constant {value}")


def _decode_json(raw: bytes, label: str, *, require_canonical: bool = False) -> Any:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise QualificationBlocked(f"{label} is not valid JSON: {error}") from error
    if require_canonical and raw != canonical_json_bytes(value):
        raise QualificationBlocked(f"{label} is not canonical JSON")
    return value


def _exact_keys(value: Any, keys: set[str] | frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise QualificationBlocked(f"{label} does not have the exact registered fields")
    return value


def _safe_relative_path(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise QualificationBlocked(f"{label} is not a safe relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise QualificationBlocked(f"{label} is not a safe relative POSIX path")
    return path


def _read_regular_file(path: Path, limit: int, label: str) -> bytes:
    try:
        before = path.lstat()
    except OSError as error:
        raise QualificationBlocked(f"{label} is unavailable") from error
    if path.is_symlink() or not path.is_file():
        raise QualificationBlocked(f"{label} must be a regular non-symlink file")
    if before.st_size > limit:
        raise QualificationBlocked(f"{label} exceeds its size cap")
    try:
        raw = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise QualificationBlocked(f"{label} cannot be read") from error
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_mode,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_mode,
    )
    if identity_before != identity_after or len(raw) != before.st_size:
        raise QualificationBlocked(f"{label} changed while it was read")
    return raw


def _source_file(root: Path, relative: PurePosixPath, label: str) -> Path:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise QualificationBlocked(f"{label} crosses a symlink")
    try:
        resolved = current.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise QualificationBlocked(f"{label} is unavailable") from error
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise QualificationBlocked(f"{label} escapes the source root") from error
    return resolved


def _manifest_hash(value: Any, field: str = "manifest_sha256") -> str:
    if not isinstance(value, dict) or field not in value:
        raise QualificationBlocked("manifest is missing its digest")
    body = {key: item for key, item in value.items() if key != field}
    measured = canonical_hash(body)
    if value[field] != measured:
        raise QualificationBlocked("manifest digest does not match its exact content")
    return measured


def _load_authority(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not _valid_hash(expected_sha256):
        raise QualificationBlocked("an external authority digest is required")
    raw = _read_regular_file(path, MAX_AUTHORITY_BYTES, "authority manifest")
    authority = _decode_json(raw, "authority manifest", require_canonical=True)
    keys = {
        "schema_version",
        "authority_id",
        "status",
        "semantic_registry",
        "candidate_manifest",
        "worker",
        "launcher",
        "toolchain",
        "runtime_identity",
        "evidence_pins",
        "bundle_files",
        "expected",
        "manifest_sha256",
    }
    authority = _exact_keys(authority, keys, "authority manifest")
    _exact_int(authority["schema_version"], SCHEMA_VERSION, "authority schema version")
    if not isinstance(authority["authority_id"], str) or not authority["authority_id"]:
        raise QualificationBlocked("authority id is missing")
    if authority["status"] != "independently_ratified":
        raise QualificationBlocked("authority manifest is not independently ratified")
    measured = _manifest_hash(authority)
    if measured != expected_sha256:
        raise QualificationBlocked("authority manifest differs from the external digest")

    semantic = _exact_keys(
        authority["semantic_registry"],
        {"path", "manifest_sha256", "ratification"},
        "semantic registry authority",
    )
    _safe_relative_path(semantic["path"], "semantic registry path")
    if not _valid_hash(semantic["manifest_sha256"]):
        raise QualificationBlocked("semantic registry digest is invalid")
    ratification = _exact_keys(
        semantic["ratification"],
        {"status", "author_id", "ratifier_id", "independent", "evidence_sha256"},
        "semantic registry ratification",
    )
    if (
        ratification["status"] != "independently_ratified"
        or ratification["independent"] is not True
        or not isinstance(ratification["author_id"], str)
        or not ratification["author_id"]
        or not isinstance(ratification["ratifier_id"], str)
        or not ratification["ratifier_id"]
        or ratification["author_id"] == ratification["ratifier_id"]
        or not _valid_hash(ratification["evidence_sha256"])
    ):
        raise QualificationBlocked("semantic registry lacks independent ratification")

    candidate = _exact_keys(
        authority["candidate_manifest"],
        {"path", "manifest_sha256"},
        "candidate manifest authority",
    )
    _safe_relative_path(candidate["path"], "candidate manifest path")
    if not _valid_hash(candidate["manifest_sha256"]):
        raise QualificationBlocked("candidate manifest digest is invalid")

    worker = _exact_keys(authority["worker"], {"path", "protocol"}, "worker authority")
    _safe_relative_path(worker["path"], "worker path")
    if worker["protocol"] != PROTOCOL:
        raise QualificationBlocked("worker protocol is not registered")

    launcher = _exact_keys(authority["launcher"], LAUNCHER_IDENTITY_KEYS, "launcher authority")
    if launcher != _launcher_identity():
        raise QualificationBlocked("launcher identity differs from external authority")

    toolchain = _exact_keys(
        authority["toolchain"], {"revision", "tree", "language_version"}, "toolchain"
    )
    if toolchain != {
        "revision": PINNED_METIS_REVISION,
        "tree": PINNED_METIS_TREE,
        "language_version": "0.43",
    }:
        raise QualificationBlocked("toolchain authority is invalid")
    runtime = _exact_keys(
        authority["runtime_identity"], RUNTIME_IDENTITY_KEYS, "runtime identity authority"
    )
    pins = _exact_keys(authority["evidence_pins"], EVIDENCE_PIN_KEYS, "evidence pins")
    if any(not _valid_hash(value) for value in pins.values()):
        raise QualificationBlocked("evidence pin is invalid")
    expected_runtime_values = {
        "node": PINNED_NODE_VERSION,
        "snapshot_revision": PINNED_METIS_REVISION,
        "snapshot_tree": PINNED_METIS_TREE,
        "tooling_package_sha256": pins["tooling_package_sha256"],
        "tooling_lock_sha256": pins["tooling_lock_sha256"],
        "node_modules_sha256": pins["node_modules_sha256"],
        "node_binary_sha256": pins["node_binary_sha256"],
        "sandbox_exec_path": "sandbox-exec:///usr/bin/sandbox-exec",
        "oracle_policy_version": "2",
        "oracle_policy_sha256": pins["oracle_policy_sha256"],
        "execution_policy_sha256": pins["execution_policy_sha256"],
    }
    if any(runtime[key] != value for key, value in expected_runtime_values.items()):
        raise QualificationBlocked("runtime identity differs from its transitive pins")
    snapshot = f"snapshot://{PINNED_METIS_REVISION}/{PINNED_METIS_TREE}"
    if (
        runtime["node_path"] != f"node://{PINNED_NODE_VERSION}"
        or runtime["loader_path"] != f"{snapshot}/.metis-oracle/native_ts_loader.mjs"
        or runtime["runner_path"] != f"{snapshot}/.metis-oracle/runner.ts"
    ):
        raise QualificationBlocked("runtime executable identities differ from the snapshot")

    expected = _exact_keys(
        authority["expected"],
        {"candidates", "executions", "roles"},
        "expected roster",
    )
    _exact_int(expected["candidates"], 3, "expected candidate count")
    _exact_int(expected["executions"], 5, "expected execution count")
    if expected["roles"] != EXPECTED_ROLE_COUNTS or any(
        type(value) is not int for value in expected["roles"].values()
    ):
        raise QualificationBlocked("authority does not describe the exact three-candidate gate")
    return authority


def _launcher_identity_v3() -> dict[str, Any]:
    injected = globals().get("__qualifier_preimage__")
    injected_path = globals().get("__qualifier_path__")
    if injected is None and injected_path is None:
        identity = _launcher_identity()
    else:
        if (
            not isinstance(injected, bytes)
            or not injected
            or len(injected) > MAX_BUNDLE_FILE_BYTES
            or not isinstance(injected_path, str)
        ):
            raise QualificationBlocked("injected qualifier preimage is invalid")
        qualifier = _strict_canonical_path(
            injected_path,
            "injected qualifier logical path",
            must_exist=True,
            directory=False,
        )
        identity = _launcher_identity_from_preimage(qualifier, injected)
    identity["sandbox_policy_template_sha256"] = V3_OUTER_SANDBOX_POLICY_TEMPLATE_SHA256
    identity["qualifier_bootstrap_sha256"] = V3_QUALIFIER_BOOTSTRAP_SHA256
    if identity["python_version"] != V3_PYTHON["version"]:
        raise QualificationBlocked("production capsule launcher requires CPython 3.13.3")
    return identity


def _validate_tree_descriptor(
    value: Any,
    *,
    kind: str,
    label: str,
) -> dict[str, Any]:
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
    descriptor = _exact_keys(value, keys, label)
    _exact_int(descriptor["schema_version"], V3_SCHEMA_VERSION, f"{label} schema version")
    if (
        not isinstance(descriptor["bundle_id"], str)
        or not descriptor["bundle_id"]
        or descriptor["kind"] != kind
    ):
        raise QualificationBlocked(f"{label} identity is invalid")
    files = descriptor["files"]
    if not isinstance(files, list) or not files:
        raise QualificationBlocked(f"{label} file roster is empty")
    seen: set[str] = set()
    total = 0
    for index, record in enumerate(files):
        record = _exact_keys(
            record,
            {"path", "size", "mode", "sha256", "role"},
            f"{label} file {index}",
        )
        relative = _safe_relative_path(record["path"], f"{label} file {index} path")
        lowered = {part.lower() for part in relative.parts}
        if (
            ".git" in lowered
            or any(part == ".env" or part.startswith(".env.") for part in lowered)
            or relative.as_posix() in {"bundle.json", "capsule.json"}
            or relative.as_posix() in seen
            or type(record["size"]) is not int
            or record["size"] < 0
            or type(record["mode"]) is not int
            or record["mode"] not in {0o444, 0o555}
            or not _valid_hash(record["sha256"])
            or not isinstance(record["role"], str)
            or not record["role"]
        ):
            raise QualificationBlocked(f"{label} file {index} is invalid")
        seen.add(relative.as_posix())
        total += record["size"]
    counts = _exact_keys(descriptor["counts"], {"files", "bytes"}, f"{label} counts")
    if counts != {"files": len(files), "bytes": total} or any(
        type(value) is not int for value in counts.values()
    ):
        raise QualificationBlocked(f"{label} counts differ from the roster")
    body = {key: item for key, item in descriptor.items() if key != "manifest_sha256"}
    if descriptor["manifest_sha256"] != canonical_hash(body):
        raise QualificationBlocked(f"{label} manifest digest is invalid")
    if kind == "source":
        if descriptor["roster_sha256"] != canonical_hash(files):
            raise QualificationBlocked("source bundle roster digest is invalid")
    else:
        python = _exact_keys(
            descriptor["python"], set(V3_PYTHON), "dependency bundle Python identity"
        )
        if python != V3_PYTHON:
            raise QualificationBlocked("dependency bundle Python ABI is not registered")
        if (
            len(files) != V3_DEPENDENCY_FILES
            or total != V3_DEPENDENCY_BYTES
            or descriptor["roster_sha256"] != V3_DEPENDENCY_ROSTER_SHA256
        ):
            raise QualificationBlocked("dependency bundle denominator or roster digest drifted")
    return descriptor


def _validate_capsule_descriptor(value: Any) -> dict[str, Any]:
    keys = {
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
    }
    capsule = _exact_keys(value, keys, "capsule authority")
    _exact_int(capsule["schema_version"], V3_SCHEMA_VERSION, "capsule schema version")
    if (
        not isinstance(capsule["capsule_id"], str)
        or not capsule["capsule_id"]
        or capsule["revision"] != PINNED_METIS_REVISION
        or capsule["tree"] != PINNED_METIS_TREE
        or capsule["language_version"] != "0.43"
    ):
        raise QualificationBlocked("capsule revision/tree/language identity is invalid")
    files = capsule["files"]
    if not isinstance(files, list) or not files:
        raise QualificationBlocked("capsule file roster is empty")
    seen: dict[str, dict[str, Any]] = {}
    total = 0
    for index, record in enumerate(files):
        record = _exact_keys(
            record,
            {"path", "size", "mode", "sha256", "role"},
            f"capsule file {index}",
        )
        path = _safe_relative_path(record["path"], f"capsule file {index} path")
        lowered = {part.lower() for part in path.parts}
        if (
            ".git" in lowered
            or any(part == ".env" or part.startswith(".env.") for part in lowered)
            or path.as_posix() == "capsule.json"
            or path.as_posix() in seen
            or type(record["size"]) is not int
            or record["size"] < 0
            or type(record["mode"]) is not int
            or record["mode"] not in {0o444, 0o555}
            or not _valid_hash(record["sha256"])
            or record["role"] not in {"git-archive", "tooling", "loader", "runner"}
        ):
            raise QualificationBlocked(f"capsule file {index} is invalid")
        seen[path.as_posix()] = record
        total += record["size"]
    counts = _exact_keys(capsule["counts"], {"files", "bytes"}, "capsule counts")
    if counts != {"files": len(files), "bytes": total}:
        raise QualificationBlocked("capsule counts differ from its roster")
    if capsule["roster_sha256"] != canonical_hash(files):
        raise QualificationBlocked("capsule roster digest is invalid")
    for label in ("loader", "runner"):
        identity = _exact_keys(capsule[label], {"path", "sha256", "mode"}, f"capsule {label}")
        row = seen.get(identity["path"])
        if (
            row is None
            or row["role"] != label
            or row["sha256"] != identity["sha256"]
            or row["mode"] != identity["mode"]
        ):
            raise QualificationBlocked(f"capsule {label} identity is not in the exact roster")
    if capsule["loader"] != {
        "path": ".metis-oracle/native_ts_loader.mjs",
        "sha256": V3_LOADER_SHA256,
        "mode": 0o444,
    }:
        raise QualificationBlocked("capsule loader is not the registered native loader")
    if capsule["runner"] != {
        "path": ".metis-oracle/runner.ts",
        "sha256": V3_RUNNER_SHA256,
        "mode": 0o444,
    }:
        raise QualificationBlocked("capsule runner is not the registered runner")
    tooling = _exact_keys(
        capsule["tooling"],
        {"package_sha256", "lock_sha256", "node_modules_sha256"},
        "capsule tooling",
    )
    expected_tooling = {
        "package_sha256": "sha256:f8130a67f948720b339695fae614f32185610f762d69b85ff600f08971f2fb80",
        "lock_sha256": "sha256:fed109b62f300ed824201f4b167d700072008b0b4a817cbb512a2eee32edc9fb",
        "node_modules_sha256": "sha256:1cea5f2f0371d3c57b9ef9787707bc1079f88dc697c7be2c6c247e4018f6e463",  # noqa: E501
    }
    if tooling != expected_tooling:
        raise QualificationBlocked("capsule tooling identity differs from its pins")
    body = {key: item for key, item in capsule.items() if key != "manifest_sha256"}
    if capsule["manifest_sha256"] != canonical_hash(body):
        raise QualificationBlocked("capsule manifest digest is invalid")
    return capsule


def _load_authority_v3(path: Path, expected_sha256: str) -> dict[str, Any]:
    path = _strict_canonical_path(
        path,
        "production authority manifest",
        must_exist=True,
        directory=False,
    )
    if not _valid_hash(expected_sha256):
        raise QualificationBlocked("an external production authority digest is required")
    raw = _read_regular_file(path, MAX_AUTHORITY_BYTES, "production authority manifest")
    authority = _decode_json(raw, "production authority manifest", require_canonical=True)
    keys = {
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
    }
    authority = _exact_keys(authority, keys, "production authority manifest")
    _exact_int(authority["schema_version"], V3_SCHEMA_VERSION, "authority schema version")
    if (
        authority["authority_id"] != V3_AUTHORITY_ID
        or authority["status"] != "independently_ratified"
        or _manifest_hash(authority) != expected_sha256
    ):
        raise QualificationBlocked("production authority identity or digest is invalid")
    ratification = _exact_keys(
        authority["ratification"],
        {"verdict", "scope", "independent", "kimi_report_sha256"},
        "production authority ratification",
    )
    if (
        ratification["verdict"] != "RATIFIABLE"
        or ratification["scope"] != ["F-1", "F-2", "F-3"]
        or ratification["independent"] is not True
        or ratification["kimi_report_sha256"] != V3_KIMI_REPORT_SHA256
    ):
        raise QualificationBlocked("production authority does not bind the exact Kimi ratification")
    project = _exact_keys(
        authority["project"],
        {"revision", "candidate_manifest", "semantic_registry", "launcher", "worker"},
        "production authority project",
    )
    if project["revision"] != V3_PROJECT_SHA:
        raise QualificationBlocked("production authority project revision drifted")
    candidate = _exact_keys(project["candidate_manifest"], {"path", "manifest_sha256"}, "candidate")
    semantic = _exact_keys(project["semantic_registry"], {"path", "manifest_sha256"}, "semantic")
    _safe_relative_path(candidate["path"], "candidate manifest path")
    _safe_relative_path(semantic["path"], "semantic registry path")
    if candidate["manifest_sha256"] != V3_CANDIDATE_MANIFEST_SHA256:
        raise QualificationBlocked("frozen candidate manifest digest drifted")
    if semantic["manifest_sha256"] != V3_SEMANTIC_REGISTRY_SHA256:
        raise QualificationBlocked("frozen semantic registry digest drifted")
    _exact_keys(project["launcher"], V3_LAUNCHER_IDENTITY_KEYS, "production launcher")
    if project["launcher"] != _launcher_identity_v3():
        raise QualificationBlocked("production launcher identity differs from authority")
    worker = _exact_keys(project["worker"], {"path", "sha256", "protocol"}, "production worker")
    _safe_relative_path(worker["path"], "production worker path")
    if worker["protocol"] != V3_PROTOCOL or not _valid_hash(worker["sha256"]):
        raise QualificationBlocked("production worker identity is invalid")
    source = _validate_tree_descriptor(
        authority["source_bundle"], kind="source", label="source bundle authority"
    )
    dependency = _validate_tree_descriptor(
        authority["dependency_bundle"], kind="dependency", label="dependency bundle authority"
    )
    capsule = _validate_capsule_descriptor(authority["capsule"])
    runtime = _exact_keys(
        authority["runtime"], {"schema_version", "node", "loader_flags"}, "runtime authority"
    )
    _exact_int(runtime["schema_version"], V3_SCHEMA_VERSION, "runtime authority schema version")
    node = _exact_keys(
        runtime["node"], {"path", "size", "source_mode", "mode", "sha256"}, "runtime Node"
    )
    if node != {
        "path": "bin/node",
        "size": V3_NODE_BINARY_BYTES,
        "source_mode": 0o755,
        "mode": 0o555,
        "sha256": V3_NODE_BINARY_SHA256,
    } or runtime["loader_flags"] != list(V3_LOADER_FLAGS):
        raise QualificationBlocked("runtime Node preimage or loader flags drifted")
    source_by_path = {item["path"]: item for item in source["files"]}
    required = {
        worker["path"]: worker["sha256"],
        candidate["path"]: None,
        semantic["path"]: None,
    }
    if any(path not in source_by_path for path in required):
        raise QualificationBlocked("source bundle omits a required production authority path")
    if source_by_path[worker["path"]]["sha256"] != worker["sha256"]:
        raise QualificationBlocked("production worker bytes differ from authority")
    expected = _exact_keys(authority["expected"], {"candidates", "executions", "roles"}, "expected")
    _exact_int(expected["candidates"], 3, "production expected candidate count")
    _exact_int(expected["executions"], 5, "production expected execution count")
    _exact_count_map(expected["roles"], EXPECTED_ROLE_COUNTS, "production expected roles")
    if authority["native_evidence"] != V3_NATIVE_EVIDENCE:
        raise QualificationBlocked("production authority native evidence binding drifted")
    if authority["non_claims"] != V3_NON_CLAIMS:
        raise QualificationBlocked("production authority overstates its claim scope")
    del dependency, capsule, runtime
    return authority


def _read_bundle_sources(
    authority: dict[str, Any], source_root: Path
) -> tuple[list[dict[str, str]], dict[str, bytes]]:
    records = authority["bundle_files"]
    if not isinstance(records, list) or not records or len(records) > 128:
        raise QualificationBlocked("bundle file roster is empty or exceeds its cap")
    material: list[dict[str, str]] = []
    contents: dict[str, bytes] = {}
    kinds: Counter[str] = Counter()
    total = 0
    for index, item in enumerate(records):
        item = _exact_keys(item, {"path", "kind", "file_sha256"}, f"bundle file {index}")
        relative = _safe_relative_path(item["path"], f"bundle file {index} path")
        kind = item["kind"]
        if kind not in REQUIRED_BUNDLE_KINDS or not _valid_hash(item["file_sha256"]):
            raise QualificationBlocked(f"bundle file {index} authority is invalid")
        name = relative.as_posix()
        if name in contents:
            raise QualificationBlocked("bundle paths are not unique")
        raw = _read_regular_file(
            _source_file(source_root, relative, f"bundle file {name}"),
            MAX_BUNDLE_FILE_BYTES,
            f"bundle file {name}",
        )
        total += len(raw)
        if total > MAX_BUNDLE_BYTES:
            raise QualificationBlocked("bundle exceeds its aggregate size cap")
        if _bytes_hash(raw) != item["file_sha256"]:
            raise QualificationBlocked(f"bundle file {name} differs from its authority")
        contents[name] = raw
        kinds[kind] += 1
        material.append({"path": name, "kind": kind, "file_sha256": item["file_sha256"]})
    if not REQUIRED_BUNDLE_KINDS.issubset(kinds):
        raise QualificationBlocked("bundle omits a required W3/schema/manifest/runner/worker kind")
    if kinds["worker"] != 1 or kinds["runner"] != 1:
        raise QualificationBlocked("bundle must contain exactly one worker and one runner")
    by_path = {item["path"]: item for item in material}
    required_paths = {
        authority["worker"]["path"]: "worker",
        authority["semantic_registry"]["path"]: "manifest",
        authority["candidate_manifest"]["path"]: "manifest",
    }
    if any(by_path.get(path, {}).get("kind") != kind for path, kind in required_paths.items()):
        raise QualificationBlocked("authority paths are not bound into the bundle roster")
    runner_record = next(item for item in material if item["kind"] == "runner")
    if authority["evidence_pins"]["runner_sha256"] != runner_record["file_sha256"]:
        raise QualificationBlocked("runner evidence pin differs from bundled runner bytes")
    return sorted(material, key=lambda item: item["path"]), contents


def _dependency_roster_digest(root: Path, files: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(files, key=lambda item: item["path"]):
        relative = _safe_relative_path(record["path"], "dependency roster path")
        raw = _read_regular_file(
            _source_file(root, relative, f"dependency file {relative.as_posix()}"),
            MAX_BUNDLE_FILE_BYTES,
            f"dependency file {relative.as_posix()}",
        )
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(raw)).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(raw).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _verify_external_tree(
    root_path: str | os.PathLike[str],
    descriptor: dict[str, Any],
    *,
    manifest_name: str,
    label: str,
) -> tuple[Path, dict[str, bytes]]:
    candidate = Path(root_path)
    if candidate.is_symlink():
        raise QualificationBlocked(f"{label} root may not be a symlink")
    try:
        root = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise QualificationBlocked(f"{label} root is unavailable") from error
    if not root.is_dir() or stat.S_IMODE(root.lstat().st_mode) != 0o555:
        raise QualificationBlocked(f"{label} root is not an immutable directory")
    raw_manifest = _read_regular_file(
        _source_file(root, PurePosixPath(manifest_name), f"{label} manifest"),
        MAX_AUTHORITY_BYTES,
        f"{label} manifest",
    )
    if raw_manifest != canonical_json_bytes(descriptor):
        raise QualificationBlocked(f"{label} manifest bytes differ from authority")
    contents: dict[str, bytes] = {}
    for record in descriptor["files"]:
        relative = _safe_relative_path(record["path"], f"{label} path")
        name = relative.as_posix()
        path = _source_file(root, relative, f"{label} file {name}")
        file_cap = 256 * 1024 * 1024 if label == "runtime capsule" else MAX_BUNDLE_FILE_BYTES
        raw = _read_regular_file(path, file_cap, f"{label} file {name}")
        if (
            len(raw) != record["size"]
            or stat.S_IMODE(path.lstat().st_mode) != record["mode"]
            or _bytes_hash(raw) != record["sha256"]
        ):
            raise QualificationBlocked(f"{label} file {name} differs from authority")
        contents[name] = raw
    items = list(root.rglob("*"))
    if any(item.is_symlink() for item in items):
        raise QualificationBlocked(f"{label} contains a symlink")
    if any(not item.is_file() and not item.is_dir() for item in items):
        raise QualificationBlocked(f"{label} contains a non-regular entry")
    actual_files = {item.relative_to(root).as_posix() for item in items if item.is_file()}
    if actual_files != set(contents) | {manifest_name}:
        raise QualificationBlocked(f"{label} has missing or extra files")
    actual_directories = {item.relative_to(root).as_posix() for item in items if item.is_dir()}
    expected_directories = _expected_tree_directories(actual_files)
    if actual_directories != expected_directories or any(
        stat.S_IMODE(item.lstat().st_mode) != 0o555 for item in items if item.is_dir()
    ):
        raise QualificationBlocked(f"{label} directory roster or mode drifted")
    if stat.S_IMODE((root / manifest_name).lstat().st_mode) != 0o444:
        raise QualificationBlocked(f"{label} manifest mode drifted")
    if descriptor.get("kind") == "dependency":
        measured = _dependency_roster_digest(root, descriptor["files"])
        if measured != descriptor["roster_sha256"] or measured != V3_DEPENDENCY_ROSTER_SHA256:
            raise QualificationBlocked("dependency bundle roster digest differs from its bytes")
    return root, contents


def _materialize_tree_preimage_v3(
    trusted_root: _AnchoredDirectory,
    *,
    kind: str,
    descriptor: dict[str, Any],
    contents: dict[str, bytes],
    manifest_name: str,
    label: str,
) -> Path:
    """Materialize only already-verified bytes into a private content address."""

    if kind not in {"source", "dependency", "capsule"}:
        raise QualificationBlocked("production preimage kind is invalid")
    trusted_root.assert_path_identity()
    manifest_sha256 = descriptor.get("manifest_sha256")
    if not _valid_hash(manifest_sha256):
        raise QualificationBlocked(f"{label} preimage lacks a content address")
    records = {record["path"]: record for record in descriptor["files"]}
    if set(records) != set(contents):
        raise QualificationBlocked(f"{label} preimage byte roster differs from authority")
    namespace: _AnchoredDirectory | None = None
    target_name = f"{kind}-{manifest_sha256[len(HASH_PREFIX) :]}"
    target: _AnchoredDirectory | None = None
    try:
        namespace = _open_child_directory(
            trusted_root,
            "preimages",
            "production preimage namespace",
            mode=0o700,
            create=True,
            exist_ok=True,
        )
        target = _open_child_directory(
            namespace,
            target_name,
            f"{label} preimage",
            mode=0o700,
            create=True,
        )
        all_files = {manifest_name: canonical_json_bytes(descriptor), **contents}
        modes = {manifest_name: 0o444, **{name: record["mode"] for name, record in records.items()}}
        for name in sorted(all_files):
            relative = _safe_relative_path(name, f"{label} preimage path")
            _write_regular_relative(
                target.descriptor,
                relative,
                all_files[name],
                f"{label} preimage file {name}",
                mode=modes[name],
            )
        _seal_directory_ancestry_descriptor(target.descriptor)
        target.mode = 0o555
        trusted_root.assert_path_identity()
        target.assert_path_identity()
        _verify_materialized_tree_preimage_v3(
            target,
            descriptor,
            contents,
            manifest_name=manifest_name,
            label=label,
        )
        target.owned_entry = False
        return target.path
    except BaseException:
        if target is not None:
            target.close()
            target = None
        raise
    finally:
        if target is not None:
            target.close()
        if namespace is not None:
            namespace.close()


def _verify_materialized_tree_preimage_v3(
    target: _AnchoredDirectory,
    descriptor: dict[str, Any],
    contents: dict[str, bytes],
    *,
    manifest_name: str,
    label: str,
) -> None:
    records = {record["path"]: record for record in descriptor["files"]}
    expected_files = set(records) | {manifest_name}
    if set(records) != set(contents):
        raise QualificationBlocked(f"{label} preimage byte roster differs from authority")
    root_metadata = os.fstat(target.descriptor)
    if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_IMODE(root_metadata.st_mode) != 0o555:
        raise QualificationBlocked(f"{label} preimage root mode changed")
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    snapshot: dict[str, bytes] = {}

    def visit(descriptor_fd: int, prefix: PurePosixPath | None = None) -> None:
        for name in sorted(os.listdir(descriptor_fd)):
            _validate_child_name(name, f"{label} preimage entry")
            relative = PurePosixPath(name) if prefix is None else prefix / name
            metadata = os.stat(name, dir_fd=descriptor_fd, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise QualificationBlocked(f"{label} preimage contains a symlink")
            if stat.S_ISDIR(metadata.st_mode):
                if stat.S_IMODE(metadata.st_mode) != 0o555:
                    raise QualificationBlocked(f"{label} preimage directory mode changed")
                actual_directories.add(relative.as_posix())
                child = -1
                try:
                    child = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor_fd)
                    visit(child, relative)
                finally:
                    if child >= 0:
                        os.close(child)
                continue
            relative_name = relative.as_posix()
            record = records.get(relative_name)
            mode = 0o444 if relative_name == manifest_name else record and record["mode"]
            if not stat.S_ISREG(metadata.st_mode) or type(mode) is not int:
                raise QualificationBlocked(f"{label} preimage roster changed")
            limit = (
                MAX_AUTHORITY_BYTES
                if relative_name == manifest_name
                else 256 * 1024 * 1024
                if label == "runtime capsule"
                else MAX_BUNDLE_FILE_BYTES
            )
            snapshot[relative_name] = _read_regular_at(
                descriptor_fd,
                name,
                limit,
                f"{label} preimage file {relative_name}",
                mode=mode,
            )
            actual_files.add(relative_name)

    target.assert_path_identity()
    visit(target.descriptor)
    target.assert_path_identity()
    if actual_files != expected_files or actual_directories != _expected_tree_directories(
        expected_files
    ):
        raise QualificationBlocked(f"{label} preimage roster changed")
    manifest = snapshot.pop(manifest_name)
    if manifest != canonical_json_bytes(descriptor) or snapshot != contents:
        raise QualificationBlocked(f"{label} preimage differs from measured bytes")
    if descriptor.get("kind") == "dependency":
        measured = hashlib.sha256()
        for record in sorted(descriptor["files"], key=lambda item: item["path"]):
            raw = snapshot[record["path"]]
            measured.update(record["path"].encode("utf-8"))
            measured.update(b"\0")
            measured.update(str(len(raw)).encode("ascii"))
            measured.update(b"\0")
            measured.update(hashlib.sha256(raw).hexdigest().encode("ascii"))
            measured.update(b"\n")
        if (
            measured.hexdigest() != descriptor["roster_sha256"]
            or measured.hexdigest() != V3_DEPENDENCY_ROSTER_SHA256
        ):
            raise QualificationBlocked("dependency preimage roster digest differs from bytes")


def _verify_tree_preimage_at_v3(
    trusted_root: _AnchoredDirectory,
    *,
    kind: str,
    descriptor: dict[str, Any],
    contents: dict[str, bytes],
    manifest_name: str,
    label: str,
) -> None:
    trusted_root.assert_path_identity()
    namespace: _AnchoredDirectory | None = None
    target: _AnchoredDirectory | None = None
    try:
        namespace = _open_child_directory(
            trusted_root,
            "preimages",
            "production preimage namespace",
            mode=0o555,
            create=False,
        )
        target = _open_child_directory(
            namespace,
            f"{kind}-{descriptor['manifest_sha256'][len(HASH_PREFIX) :]}",
            f"{label} preimage",
            mode=0o555,
            create=False,
        )
        _verify_materialized_tree_preimage_v3(
            target,
            descriptor,
            contents,
            manifest_name=manifest_name,
            label=label,
        )
        trusted_root.assert_path_identity()
    finally:
        if target is not None:
            target.close()
        if namespace is not None:
            namespace.close()


def _materialize_runtime_node_v3(
    runtime_root: _AnchoredDirectory,
    source_node: Path,
    descriptor: dict[str, Any],
) -> Path:
    """Capture the exact registered Node bytes into the sealed runtime root."""

    source_node = _strict_canonical_path(
        source_node, "registered Node source", must_exist=True, directory=False
    )
    source_metadata = source_node.lstat()
    if (
        source_node.is_symlink()
        or not stat.S_ISREG(source_metadata.st_mode)
        or source_metadata.st_nlink != 1
        or stat.S_IMODE(source_metadata.st_mode) != descriptor["source_mode"]
        or source_metadata.st_size != descriptor["size"]
    ):
        raise QualificationBlocked("registered Node source metadata drifted")
    raw = _read_regular_file(
        source_node,
        RETAINED_ROOT_CAPS["production-runtime-root"][3],
        "registered Node source",
    )
    if len(raw) != descriptor["size"] or _bytes_hash(raw) != descriptor["sha256"]:
        raise QualificationBlocked("registered Node source bytes drifted")
    relative = _safe_relative_path(descriptor["path"], "runtime Node path")
    runtime_root.assert_path_identity()
    _write_regular_relative(
        runtime_root.descriptor,
        relative,
        raw,
        "retained runtime Node",
        mode=descriptor["mode"],
    )
    _seal_retained_tree(runtime_root.descriptor, "production-runtime-root")
    runtime_root.mode = 0o555
    runtime_root.assert_path_identity()
    retained = _source_file(runtime_root.path, relative, "retained runtime Node")
    retained_metadata = retained.lstat()
    retained_raw = _read_regular_file(
        retained,
        RETAINED_ROOT_CAPS["production-runtime-root"][3],
        "retained runtime Node",
    )
    if (
        stat.S_IMODE(retained_metadata.st_mode) != descriptor["mode"]
        or len(retained_raw) != descriptor["size"]
        or _bytes_hash(retained_raw) != descriptor["sha256"]
    ):
        raise QualificationBlocked("retained runtime Node differs from authority")
    roster, counts = _snapshot_retained_tree(runtime_root.descriptor, "production-runtime-root")
    if counts != {"files": 1, "directories": 2, "bytes": descriptor["size"]} or not roster:
        raise QualificationBlocked("retained runtime root roster is not exact")
    return retained


def _verify_runtime_node_v3(
    runtime_root: _AnchoredDirectory,
    descriptor: dict[str, Any],
) -> Path:
    runtime_root.assert_path_identity()
    relative = _safe_relative_path(descriptor["path"], "runtime Node path")
    retained = _source_file(runtime_root.path, relative, "retained runtime Node")
    metadata = retained.lstat()
    raw = _read_regular_file(
        retained,
        RETAINED_ROOT_CAPS["production-runtime-root"][3],
        "retained runtime Node",
    )
    if (
        stat.S_IMODE(metadata.st_mode) != descriptor["mode"]
        or len(raw) != descriptor["size"]
        or _bytes_hash(raw) != descriptor["sha256"]
    ):
        raise QualificationBlocked("retained runtime Node changed")
    roster, counts = _snapshot_retained_tree(runtime_root.descriptor, "production-runtime-root")
    if counts != {"files": 1, "directories": 2, "bytes": descriptor["size"]} or not roster:
        raise QualificationBlocked("retained runtime root roster changed")
    return retained


def _seal_preimage_namespace_v3(trusted_root: _AnchoredDirectory) -> Path:
    namespace: _AnchoredDirectory | None = None
    try:
        namespace = _open_child_directory(
            trusted_root,
            "preimages",
            "production preimage namespace",
            mode=0o700,
            create=False,
        )
        os.fchmod(namespace.descriptor, 0o555)
        namespace.mode = 0o555
        os.fchmod(trusted_root.descriptor, 0o555)
        trusted_root.mode = 0o555
        namespace.assert_path_identity()
        trusted_root.assert_path_identity()
        return namespace.path
    finally:
        if namespace is not None:
            namespace.close()


def _verify_materialized_bundle(
    bundle: _AnchoredDirectory,
    bundle_body: dict[str, Any],
    contents: dict[str, bytes],
    *,
    immutable: bool = True,
) -> None:
    directory_mode = 0o555 if immutable else 0o700
    file_mode = 0o444 if immutable else 0o600
    expected_files = set(contents) | {"bundle.json"}
    root_metadata = os.fstat(bundle.descriptor)
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_IMODE(root_metadata.st_mode) != directory_mode
    ):
        raise QualificationBlocked("materialized bundle root mode changed")
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    snapshot: dict[str, bytes] = {}
    total = 0

    def visit(descriptor: int, prefix: PurePosixPath | None = None) -> None:
        nonlocal total
        for name in sorted(os.listdir(descriptor)):
            _validate_child_name(name, "materialized bundle entry")
            relative = PurePosixPath(name) if prefix is None else prefix / name
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise QualificationBlocked("materialized bundle contains a symlink")
            if stat.S_ISDIR(metadata.st_mode):
                if stat.S_IMODE(metadata.st_mode) != directory_mode:
                    raise QualificationBlocked("materialized bundle directory mode changed")
                actual_directories.add(relative.as_posix())
                child = -1
                try:
                    child = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
                    visit(child, relative)
                finally:
                    if child >= 0:
                        os.close(child)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise QualificationBlocked("materialized bundle roster changed")
            relative_name = relative.as_posix()
            actual_files.add(relative_name)
            limit = MAX_AUTHORITY_BYTES if relative_name == "bundle.json" else MAX_BUNDLE_FILE_BYTES
            raw = _read_regular_at(
                descriptor,
                name,
                limit,
                f"materialized bundle file {relative_name}",
                mode=file_mode,
            )
            total += len(raw)
            if total > MAX_BUNDLE_BYTES + MAX_AUTHORITY_BYTES:
                raise QualificationBlocked("materialized bundle exceeds its aggregate size cap")
            snapshot[relative_name] = raw

    visit(bundle.descriptor)
    if actual_files != expected_files or actual_directories != _expected_tree_directories(
        expected_files
    ):
        raise QualificationBlocked("materialized bundle roster changed")
    if snapshot.pop("bundle.json") != canonical_json_bytes(bundle_body):
        raise QualificationBlocked("materialized bundle metadata changed")
    if snapshot != contents:
        raise QualificationBlocked("materialized bundle bytes changed")


def _materialize_bundle(
    artifact_root: _AnchoredDirectory,
    authority_sha256: str,
    material: list[dict[str, str]],
    contents: dict[str, bytes],
) -> tuple[Path, str, dict[str, Any]]:
    bundle_core = {
        "schema_version": SCHEMA_VERSION,
        "authority_manifest_sha256": authority_sha256,
        "files": material,
    }
    bundle_sha256 = canonical_hash(bundle_core)
    bundle_body = {**bundle_core, "bundle_sha256": bundle_sha256}
    bundles: _AnchoredDirectory | None = None
    target_name = bundle_sha256[len(HASH_PREFIX) :]
    target: _AnchoredDirectory | None = None
    try:
        bundles = _open_child_directory(
            artifact_root,
            "bundles",
            "bundle namespace",
            mode=0o700,
            create=True,
            exist_ok=True,
        )
        target = _open_existing_materialized_bundle(bundles, target_name)
        if target is None:
            target = _open_child_directory(
                bundles,
                target_name,
                "materialized bundle",
                mode=0o700,
                create=True,
            )
            for name, raw in sorted(contents.items()):
                _write_regular_relative(
                    target.descriptor,
                    _safe_relative_path(name, "bundle publication path"),
                    raw,
                    f"bundled file {name}",
                )
            _write_regular_relative(
                target.descriptor,
                PurePosixPath("bundle.json"),
                canonical_json_bytes(bundle_body),
                "bundle metadata",
            )
            artifact_root.assert_path_identity()
            target.assert_path_identity()
            _verify_materialized_bundle(target, bundle_body, contents, immutable=False)
            _seal_directory_descriptor(target.descriptor)
            target.mode = 0o555
            artifact_root.assert_path_identity()
            target.assert_path_identity()
            _verify_materialized_bundle(target, bundle_body, contents)
            target.owned_entry = False
        else:
            artifact_root.assert_path_identity()
            target.assert_path_identity()
            _verify_materialized_bundle(target, bundle_body, contents)
        return target.path, bundle_sha256, bundle_body
    finally:
        if target is not None:
            target.close()
        if bundles is not None:
            bundles.close()


def _open_existing_materialized_bundle(
    bundles: _AnchoredDirectory,
    target_name: str,
) -> _AnchoredDirectory | None:
    try:
        return _open_child_directory(
            bundles,
            target_name,
            "existing materialized bundle",
            mode=0o555,
            create=False,
        )
    except QualificationBlocked as error:
        if not isinstance(error.__cause__, FileNotFoundError):
            raise
        return None


def _canonical_workspace(value: Any, filename: str) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        raise QualificationBlocked("semantic workspace_sources is not an object")
    result: list[dict[str, str]] = []
    for name, source in sorted(value.items()):
        relative = _safe_relative_path(name, "workspace source")
        if (
            SEMANTIC_FILENAME_PATTERN.fullmatch(name) is None
            or name == filename
            or not isinstance(source, str)
            or not source
            or relative.as_posix() != name
        ):
            raise QualificationBlocked("workspace source is invalid")
        result.append({"filename": name, "source": source})
    return result


def _candidate_content(candidate: dict[str, Any]) -> dict[str, Any]:
    family = candidate.get("family")
    if family == "F-1":
        fields = ("request", "target_source")
    elif family == "F-2":
        fields = ("before_source", "after_source", "expected_delta")
    elif family == "F-3":
        fields = ("mutated_source", "expected_diagnostic", "fixed_source", "mutation_spec")
    else:
        raise QualificationBlocked("candidate family is not supported")
    if any(field not in candidate for field in fields):
        raise QualificationBlocked("candidate content is incomplete")
    return {field: candidate[field] for field in fields}


def _exact_count_map(value: Any, expected: dict[str, int], label: str) -> None:
    value = _exact_keys(value, set(expected), label)
    for key, count in expected.items():
        _exact_int(value[key], count, f"{label} {key}")


def _validate_diagnostics(
    value: Any, label: str, *, expected_filename: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    diagnostics = _exact_keys(value, {"parser", "link", "validation", "all"}, label)
    for channel, rows in diagnostics.items():
        if not isinstance(rows, list):
            raise QualificationBlocked(f"{label} {channel} is not a diagnostic list")
        for index, row in enumerate(rows):
            row = _exact_keys(
                row,
                {"filename", "message", "severity", "code", "range"},
                f"{label} {channel} diagnostic {index}",
            )
            filename = row["filename"]
            severity = row["severity"]
            code = row["code"]
            if (
                not isinstance(filename, str)
                or SEMANTIC_FILENAME_PATTERN.fullmatch(filename) is None
                or _safe_relative_path(filename, "diagnostic filename").as_posix() != filename
                or (expected_filename is not None and filename != expected_filename)
                or not isinstance(row["message"], str)
                or (severity is not None and type(severity) is not int)
                or (code is not None and type(code) not in {str, int})
            ):
                raise QualificationBlocked(f"{label} contains a malformed diagnostic")
    return diagnostics


def _validate_failure(value: Any, label: str) -> dict[str, str]:
    failure = _exact_keys(value, {"kind", "message"}, label)
    if (
        not isinstance(failure["kind"], str)
        or not failure["kind"]
        or not isinstance(failure["message"], str)
    ):
        raise QualificationBlocked(f"{label} is malformed")
    return failure


def _validate_registered_semantic_endpoint(family: str, semantic_spec: dict[str, Any]) -> None:
    semantic_spec = _exact_keys(
        semantic_spec,
        {
            "schema_version",
            "contract",
            "filename",
            "execution_mode",
            "endpoint",
            "workspace_sources",
            "truth",
            "provenance",
        },
        "semantic specification",
    )
    _exact_int(semantic_spec.get("schema_version"), 1, "semantic spec schema version")
    if semantic_spec.get("execution_mode") != "endpoint":
        raise QualificationBlocked("bounded qualification supports endpoint mode only")
    endpoint = semantic_spec.get("endpoint")
    truth = semantic_spec.get("truth")
    if (
        not isinstance(endpoint, str)
        or not endpoint
        or not isinstance(truth, dict)
        or truth.get("expected_endpoint") != endpoint
    ):
        raise QualificationBlocked("semantic endpoint differs from registered truth")
    provenance = _exact_keys(
        semantic_spec.get("provenance"),
        {"author", "method", "review_status"},
        "semantic provenance",
    )
    if (
        not isinstance(provenance["author"], str)
        or not provenance["author"]
        or provenance["method"] != "manual_contract_review"
        or provenance["review_status"] != "candidate_for_independent_review"
    ):
        raise QualificationBlocked("semantic provenance is invalid")
    if family == "F-1":
        if semantic_spec["contract"] != "F-1-author":
            raise QualificationBlocked("semantic family contract is invalid")
        truth = _exact_keys(
            truth,
            {
                "request_exact",
                "required_source_fragments",
                "expected_endpoint",
                "expected_ir",
            },
            "F-1 semantic truth",
        )
        fragments = truth["required_source_fragments"]
        if (
            not isinstance(truth["request_exact"], str)
            or not truth["request_exact"]
            or not isinstance(fragments, list)
            or not fragments
            or any(not isinstance(item, str) or not item for item in fragments)
            or len(set(fragments)) != len(fragments)
        ):
            raise QualificationBlocked("F-1 semantic truth is invalid")
        registered_irs = (truth.get("expected_ir"),)
    elif family == "F-2":
        if semantic_spec["contract"] != "F-2-minimal-edit":
            raise QualificationBlocked("semantic family contract is invalid")
        truth = _exact_keys(
            truth,
            {
                "old_text",
                "new_text",
                "occurrences",
                "expected_endpoint",
                "expected_before_ir",
                "expected_after_ir",
                "expected_changed_paths",
            },
            "F-2 semantic truth",
        )
        _exact_int(truth["occurrences"], 1, "F-2 occurrence count")
        if (
            not isinstance(truth["old_text"], str)
            or not truth["old_text"]
            or not isinstance(truth["new_text"], str)
            or not truth["new_text"]
            or truth["old_text"] == truth["new_text"]
            or truth["expected_changed_paths"] != ["variants[0].takes[0].count.take"]
        ):
            raise QualificationBlocked("F-2 semantic truth is invalid")
        registered_irs = (truth.get("expected_before_ir"), truth.get("expected_after_ir"))
    elif family == "F-3":
        if semantic_spec["contract"] != "F-3-diagnostic-repair":
            raise QualificationBlocked("semantic family contract is invalid")
        truth = _exact_keys(
            truth,
            {
                "expected_failure_kind",
                "expected_diagnostic_present",
                "expected_endpoint",
                "repair_fragment",
                "expected_failure",
                "expected_diagnostics",
                "expected_fixed_ir",
            },
            "F-3 semantic truth",
        )
        expected_failure = _validate_failure(truth["expected_failure"], "F-3 expected failure")
        expected_diagnostics = _validate_diagnostics(
            truth["expected_diagnostics"],
            "F-3 expected diagnostics",
            expected_filename=semantic_spec["filename"],
        )
        failure_channel = {
            "parse": "parser",
            "link": "link",
            "validation": "validation",
        }.get(truth["expected_failure_kind"])
        if (
            failure_channel is None
            or truth["expected_diagnostic_present"] is not True
            or not isinstance(truth["repair_fragment"], str)
            or not truth["repair_fragment"]
            or expected_failure["kind"] != truth["expected_failure_kind"]
            or not expected_diagnostics[failure_channel]
            or not expected_diagnostics["all"]
        ):
            raise QualificationBlocked("F-3 semantic truth is invalid")
        registered_irs = (truth.get("expected_fixed_ir"),)
    else:
        raise QualificationBlocked("candidate family is not supported")
    if any(not isinstance(ir, dict) or ir.get("name") != endpoint for ir in registered_irs):
        raise QualificationBlocked("registered IR endpoint name differs from semantic endpoint")


def _load_gate_inputs(
    authority: dict[str, Any], contents: dict[str, bytes]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    candidate_path = authority["candidate_manifest"]["path"]
    registry_path = authority["semantic_registry"]["path"]
    candidates = _decode_json(contents[candidate_path], "candidate manifest")
    registry = _decode_json(contents[registry_path], "semantic registry")
    if _manifest_hash(candidates) != authority["candidate_manifest"]["manifest_sha256"]:
        raise QualificationBlocked("candidate manifest differs from authority")
    if _manifest_hash(registry) != authority["semantic_registry"]["manifest_sha256"]:
        raise QualificationBlocked("semantic registry differs from authority")
    candidates = _exact_keys(
        candidates,
        {
            "schema_version",
            "manifest_id",
            "status",
            "claim",
            "counts",
            "candidates",
            "manifest_sha256",
        },
        "candidate manifest",
    )
    registry = _exact_keys(
        registry,
        {"schema_version", "registry_id", "review_status", "counts", "specs", "manifest_sha256"},
        "semantic registry",
    )
    _exact_int(candidates["schema_version"], 1, "candidate manifest schema version")
    _exact_int(registry["schema_version"], 1, "semantic registry schema version")
    if (
        candidates["manifest_id"] != "w3-f1-f3-smoke-candidates-v1"
        or candidates["claim"] != "no_accuracy_claim"
        or registry["registry_id"] != "w3-f1-f3-smoke-semantic-specs-v1"
    ):
        raise QualificationBlocked("candidate or semantic manifest identity is invalid")
    candidate_rows = candidates.get("candidates") if isinstance(candidates, dict) else None
    specs = registry.get("specs") if isinstance(registry, dict) else None
    if not isinstance(candidate_rows, list) or not isinstance(specs, list):
        raise QualificationBlocked("candidate or semantic roster is missing")
    if len(candidate_rows) != 3 or len(specs) != 3:
        raise QualificationBlocked("candidate and semantic rosters must contain exactly three rows")
    expected_manifest_counts = {"in": 3, "out": 3, "distinct": 3, "gaps": 0}
    _exact_count_map(candidates.get("counts"), expected_manifest_counts, "candidate counts")
    _exact_count_map(registry.get("counts"), expected_manifest_counts, "semantic counts")
    if (
        candidates.get("status") != "proposed_for_independent_review"
        or registry.get("review_status") != "candidate_for_independent_review"
    ):
        raise QualificationBlocked("candidate or semantic manifest overstates its review state")
    candidates_by_id: dict[str, dict[str, Any]] = {}
    specs_by_id: dict[str, dict[str, Any]] = {}
    for candidate in candidate_rows:
        if (
            not isinstance(candidate, dict)
            or not isinstance(candidate.get("candidate_id"), str)
            or CANDIDATE_ID_PATTERN.fullmatch(candidate["candidate_id"]) is None
        ):
            raise QualificationBlocked("candidate roster contains an invalid row")
        if candidate["candidate_id"] in candidates_by_id:
            raise QualificationBlocked("candidate ids are not unique")
        candidates_by_id[candidate["candidate_id"]] = candidate
    for spec in specs:
        if (
            not isinstance(spec, dict)
            or not isinstance(spec.get("candidate_id"), str)
            or CANDIDATE_ID_PATTERN.fullmatch(spec["candidate_id"]) is None
        ):
            raise QualificationBlocked("semantic roster contains an invalid row")
        if spec["candidate_id"] in specs_by_id:
            raise QualificationBlocked("semantic ids are not unique")
        specs_by_id[spec["candidate_id"]] = spec
    if set(candidates_by_id) != set(specs_by_id):
        raise QualificationBlocked("candidate and semantic rosters differ")
    if {item.get("family") for item in candidate_rows} != set(ROLE_CONTRACT):
        raise QualificationBlocked("candidate roster does not cover F-1/F-2/F-3 exactly")

    executions: list[dict[str, Any]] = []
    for candidate_id in sorted(candidates_by_id):
        candidate = candidates_by_id[candidate_id]
        spec = specs_by_id[candidate_id]
        semantic_spec = spec.get("semantic_spec")
        spec_body = {key: item for key, item in spec.items() if key != "spec_sha256"}
        if (
            spec.get("family") != candidate.get("family")
            or spec.get("spec_sha256") != canonical_hash(spec_body)
            or spec.get("content_sha256") != canonical_hash(_candidate_content(candidate))
            or candidate.get("root_evidence", {}).get("content_sha256")
            != spec.get("content_sha256")
            or spec.get("semantic_spec_sha256") != canonical_hash(semantic_spec)
            or candidate.get("semantic_spec") != semantic_spec
            or candidate.get("root_evidence", {}).get("semantic_spec_sha256")
            != spec.get("semantic_spec_sha256")
        ):
            raise QualificationBlocked("candidate is not bound to its registered exact content")
        if not isinstance(semantic_spec, dict):
            raise QualificationBlocked("semantic specification is missing")
        _validate_registered_semantic_endpoint(candidate["family"], semantic_spec)
        filename = semantic_spec.get("filename")
        mode = semantic_spec.get("execution_mode")
        endpoint = semantic_spec.get("endpoint")
        if (
            not isinstance(filename, str)
            or SEMANTIC_FILENAME_PATTERN.fullmatch(filename) is None
            or _safe_relative_path(filename, "semantic filename").as_posix() != filename
            or mode != "endpoint"
            or not isinstance(endpoint, str)
            or not endpoint
        ):
            raise QualificationBlocked("semantic execution contract is invalid")
        workspace = _canonical_workspace(semantic_spec.get("workspace_sources"), filename)
        for role, source_field, expected_status in ROLE_CONTRACT[candidate["family"]]:
            source = candidate.get(source_field)
            if not isinstance(source, str) or not source:
                raise QualificationBlocked("candidate role source is missing")
            request = {
                "schema_version": 1,
                "source": source,
                "filename": filename,
                "execution_mode": mode,
                "endpoint": endpoint,
                "metis_root": (
                    f"snapshot://{authority['toolchain']['revision']}/"
                    f"{authority['toolchain']['tree']}"
                ),
                "metis_revision": authority["toolchain"]["revision"],
                "metis_tree": authority["toolchain"]["tree"],
                "workspace_sources": workspace,
            }
            executions.append(
                {
                    "candidate_id": candidate_id,
                    "family": candidate["family"],
                    "role": role,
                    "expected_status": expected_status,
                    "request": request,
                }
            )
    if len(executions) != 5:
        raise QualificationBlocked("derived execution roster is not exact")
    return candidates_by_id, specs_by_id, executions


def _worker_input(
    authority: dict[str, Any],
    authority_sha256: str,
    bundle_sha256: str,
    executions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL,
        "authority_manifest_sha256": authority_sha256,
        "bundle_sha256": bundle_sha256,
        "candidate_manifest_sha256": authority["candidate_manifest"]["manifest_sha256"],
        "semantic_registry_sha256": authority["semantic_registry"]["manifest_sha256"],
        "toolchain": authority["toolchain"],
        "runtime_identity": authority["runtime_identity"],
        "evidence_pins": authority["evidence_pins"],
        "executions": executions,
    }


_CHILD_BOOTSTRAP = """
import errno
import os
import resource
import runpy
import socket
import sys

bundle = os.environ["W3_QUALIFIER_BUNDLE"]
worker = os.environ["W3_QUALIFIER_WORKER"]
output_root = os.environ["W3_QUALIFIER_OUTPUT_ROOT"]
denied_path = os.environ["W3_QUALIFIER_DENIED_PATH"]
denied_read_path = os.environ["W3_QUALIFIER_DENIED_READ_PATH"]
limit = int(os.environ["W3_QUALIFIER_FILE_LIMIT"])
resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
os.umask(0o077)

try:
    descriptor = os.open(denied_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except OSError as error:
    if error.errno not in {errno.EPERM, errno.EACCES}:
        raise SystemExit(61)
else:
    os.close(descriptor)
    raise SystemExit(62)

try:
    descriptor = os.open(denied_read_path, os.O_RDONLY)
except OSError as error:
    if error.errno not in {errno.EPERM, errno.EACCES}:
        raise SystemExit(65)
else:
    os.close(descriptor)
    raise SystemExit(66)

for operation in ("bind", "connect"):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if operation == "bind":
                sock.bind(("127.0.0.1", 0))
            else:
                sock.connect(("127.0.0.1", 0))
        finally:
            sock.close()
    except OSError as error:
        if error.errno not in {errno.EPERM, errno.EACCES}:
            raise SystemExit(63)
    else:
        raise SystemExit(64)

stdlib = [entry for entry in sys.path if entry and "site-packages" not in entry]
sys.path[:] = [bundle, *stdlib]
os.chdir(bundle)
sys.argv = [worker]
runpy.run_path(worker, run_name="__main__")
""".strip()


def _kill_and_reap_process_group(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired as error:
        raise QualificationBlocked("worker process group could not be reaped") from error
    deadline = time.monotonic() + 2
    while True:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        if time.monotonic() >= deadline:
            raise QualificationBlocked("worker descendants remained after process-group kill")
        time.sleep(0.01)


def _bridge_child_supervision(role: str) -> dict[str, Any]:
    """Return Popen controls for a child registered with the bridge before exec."""

    control_fd = globals().get("__bridge_control_fd__")
    control_nonce = globals().get("__bridge_control_nonce__")
    if control_fd is None and control_nonce is None:
        return {"start_new_session": True}
    if (
        type(control_fd) is not int
        or control_fd < 3
        or not isinstance(control_nonce, str)
        or re.fullmatch(r"[0-9a-f]{64}", control_nonce) is None
        or not isinstance(role, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}", role) is None
    ):
        raise QualificationBlocked("bridge child supervision identity is invalid")
    try:
        if not stat.S_ISSOCK(os.fstat(control_fd).st_mode):
            raise QualificationBlocked("bridge child supervision channel is not a socket")
    except OSError as error:
        raise QualificationBlocked("bridge child supervision channel is unavailable") from error

    def register_before_exec() -> None:
        try:
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)
            os.setsid()
            pid = os.getpid()
            pgid = os.getpgrp()
            sid = os.getsid(0)
            registration = f"REGISTER {control_nonce} {role} {pid} {pgid} {sid}\n".encode("ascii")
            pending = memoryview(registration)
            while pending:
                written = os.write(control_fd, pending)
                if written <= 0:
                    os._exit(125)
                pending = pending[written:]
            acknowledgement = bytearray()
            while b"\n" not in acknowledgement:
                chunk = os.read(control_fd, 512 - len(acknowledgement))
                if not chunk:
                    os._exit(125)
                acknowledgement.extend(chunk)
                if len(acknowledgement) >= 512:
                    os._exit(125)
            if acknowledgement != f"ACK {control_nonce} {pid}\n".encode("ascii"):
                os._exit(125)
            os.close(control_fd)
        except BaseException:
            os._exit(125)

    return {
        "pass_fds": (control_fd,),
        "preexec_fn": register_before_exec,
        "start_new_session": False,
    }


def _run_worker(
    bundle: Path,
    worker_relative: str,
    source_root: Path,
    artifact_root: _AnchoredDirectory,
    request_bytes: bytes,
    timeout_seconds: float,
    registry: _RetainedRootRegistry,
) -> tuple[bytes, _AnchoredDirectory]:
    if len(request_bytes) > MAX_WORKER_INPUT_BYTES:
        raise QualificationBlocked("worker input exceeds its size cap")
    process: _AnchoredDirectory | None = None
    try:
        process = _create_random_directory(
            artifact_root,
            ".w3-worker-",
            "worker process root",
            registry=registry,
            kind="worker-process-root",
            logical_root="process",
            anchor="artifact-root",
        )
        output: _AnchoredDirectory | None = None
        try:
            output = _open_child_directory(
                process,
                "output",
                "worker output root",
                mode=0o700,
                create=True,
            )
            output_root = output.path
        finally:
            if output is not None:
                output.close()
        return _run_worker_with_process(
            bundle=bundle,
            worker_relative=worker_relative,
            source_root=source_root,
            artifact_root=artifact_root,
            request_bytes=request_bytes,
            timeout_seconds=timeout_seconds,
            process=process,
            output_root=output_root,
        )
    except BaseException:
        if process is not None:
            process.close()
        raise


def _run_worker_with_process(
    *,
    bundle: Path,
    worker_relative: str,
    source_root: Path,
    artifact_root: _AnchoredDirectory,
    request_bytes: bytes,
    timeout_seconds: float,
    process: _AnchoredDirectory,
    output_root: Path,
) -> tuple[bytes, _AnchoredDirectory]:
    denied_name = f".w3-denied-{process.name}"
    denied_path = artifact_root.path / denied_name
    denied_read_path = source_root / worker_relative
    if _entry_exists_at(artifact_root, denied_name):
        process.close()
        raise QualificationBlocked("external-write canary path already exists")
    environment = {
        "LANG": "C",
        "LC_ALL": "C",
        "W3_QUALIFIER_BUNDLE": str(bundle),
        "W3_QUALIFIER_WORKER": str(bundle / worker_relative),
        "W3_QUALIFIER_OUTPUT_ROOT": str(output_root),
        "W3_QUALIFIER_DENIED_PATH": str(denied_path),
        "W3_QUALIFIER_DENIED_READ_PATH": str(denied_read_path),
        "W3_QUALIFIER_FILE_LIMIT": str(MAX_WORKER_STDOUT_BYTES),
        "W3_QUALIFIER_PROTOCOL": PROTOCOL,
    }
    launcher = _launcher_identity()
    python_root = Path(launcher["python_executable"]).parent.parent.resolve(strict=True)
    command = [
        launcher["sandbox_exec_path"],
        "-p",
        OUTER_SANDBOX_POLICY_TEMPLATE,
        "-D",
        f"PROCESS_ROOT={process.path}",
        "-D",
        f"PYTHON_EXECUTABLE={launcher['python_executable']}",
        "-D",
        f"PYTHON_ROOT={python_root}",
        "-D",
        f"BUNDLE_ROOT={bundle.resolve(strict=True)}",
        "-D",
        f"SOURCE_ROOT={source_root.resolve(strict=True)}",
        "-D",
        f"ARTIFACT_ROOT={artifact_root.path}",
        launcher["python_executable"],
        "-I",
        "-S",
        "-B",
        "-c",
        _CHILD_BOOTSTRAP,
    ]
    child: subprocess.Popen[bytes] | None = None
    supervision_complete = False
    stdout_descriptor = -1
    stderr_descriptor = -1
    try:
        artifact_root.assert_path_identity()
        process.assert_path_identity()
        stdout_descriptor = os.open(
            "stdout.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=process.descriptor,
        )
        stderr_descriptor = os.open(
            "stderr.txt",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=process.descriptor,
        )
        with (
            os.fdopen(stdout_descriptor, "wb") as stdout,
            os.fdopen(stderr_descriptor, "wb") as stderr,
        ):
            stdout_descriptor = -1
            stderr_descriptor = -1
            child = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                cwd=bundle,
                env=environment,
                start_new_session=True,
            )
            try:
                child.communicate(input=request_bytes, timeout=timeout_seconds)
            except subprocess.TimeoutExpired as error:
                _kill_and_reap_process_group(child)
                supervision_complete = True
                raise QualificationBlocked("worker exceeded the timeout cap") from error
            returncode = child.returncode
            _kill_and_reap_process_group(child)
            supervision_complete = True
    except subprocess.TimeoutExpired as error:
        process.close()
        raise QualificationBlocked("worker exceeded the timeout cap") from error
    except (OSError, subprocess.SubprocessError) as error:
        process.close()
        raise QualificationBlocked("worker could not start in a clean process") from error
    except QualificationBlocked:
        process.close()
        raise
    finally:
        cleanup_error: QualificationBlocked | None = None
        if child is not None and not supervision_complete:
            try:
                _kill_and_reap_process_group(child)
            except QualificationBlocked as error:
                cleanup_error = error
        if stdout_descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(stdout_descriptor)
        if stderr_descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(stderr_descriptor)
        if cleanup_error is not None:
            raise cleanup_error
    if _entry_exists_at(artifact_root, denied_name):
        process.close()
        raise QualificationBlocked("sandbox allowed the external-write canary")
    try:
        artifact_root.assert_path_identity()
        process.assert_path_identity()
        stdout_bytes = _read_regular_at(
            process.descriptor,
            "stdout.json",
            MAX_WORKER_STDOUT_BYTES,
            "worker stdout",
            mode=0o600,
        )
        stderr_bytes = _read_regular_at(
            process.descriptor,
            "stderr.txt",
            MAX_WORKER_STDERR_BYTES,
            "worker stderr",
            mode=0o600,
        )
        if returncode != 0:
            raise QualificationBlocked(f"worker failed with exit status {returncode}")
        if stderr_bytes:
            raise QualificationBlocked("worker emitted unregistered stderr")
    except Exception:
        process.close()
        raise
    return stdout_bytes, process


_V3_CHILD_BOOTSTRAP = r"""
import errno
import json
import os
import resource
import runpy
import socket
import subprocess
import sys

source = os.environ["W3_PRODUCTION_SOURCE_BUNDLE"]
dependency = os.environ["W3_PRODUCTION_DEPENDENCY_BUNDLE"]
worker = os.environ["W3_PRODUCTION_WORKER"]
denied_write = os.environ["W3_PRODUCTION_DENIED_WRITE"]
denied_read = os.environ["W3_PRODUCTION_DENIED_READ"]
denied_preimages = (
    os.environ["W3_PRODUCTION_DENIED_SOURCE_WRITE"],
    os.environ["W3_PRODUCTION_DENIED_DEPENDENCY_WRITE"],
)
limit = int(os.environ["W3_PRODUCTION_FILE_LIMIT"])
resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
os.umask(0o077)

try:
    descriptor = os.open(denied_write, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except OSError as error:
    if error.errno not in {errno.EPERM, errno.EACCES}:
        raise SystemExit(71)
else:
    os.close(descriptor)
    raise SystemExit(72)

try:
    descriptor = os.open(denied_read, os.O_RDONLY)
except OSError as error:
    if error.errno not in {errno.EPERM, errno.EACCES}:
        raise SystemExit(73)
else:
    os.close(descriptor)
    raise SystemExit(74)

for denied_preimage in denied_preimages:
    try:
        descriptor = os.open(denied_preimage, os.O_WRONLY)
    except OSError as error:
        if error.errno not in {errno.EPERM, errno.EACCES}:
            raise SystemExit(78)
    else:
        os.close(descriptor)
        raise SystemExit(79)

for operation in ("connect", "bind"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if operation == "connect":
            sock.connect(("127.0.0.1", 0))
        else:
            sock.bind(("127.0.0.1", 0))
    except OSError as error:
        if error.errno not in {errno.EPERM, errno.EACCES}:
            raise SystemExit(75)
    else:
        raise SystemExit(76)
    finally:
        sock.close()

try:
    subprocess.run(["/usr/bin/true"], check=False, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=2)
except (OSError, subprocess.SubprocessError):
    pass
else:
    raise SystemExit(77)

stdlib = [entry for entry in sys.path if entry and "site-packages" not in entry]
sys.path[:] = [os.path.join(source, "src"), dependency, *stdlib]
os.chdir(source)
sys.argv = [worker]
runpy.run_path(worker, run_name="__main__")
""".strip()


def _run_worker_v3(
    *,
    source_bundle: Path,
    dependency_bundle: Path,
    worker_relative: str,
    authority_path: Path,
    artifact_root: _AnchoredDirectory,
    process_root: _AnchoredDirectory,
    request_bytes: bytes,
    timeout_seconds: float,
) -> bytes:
    if len(request_bytes) > MAX_WORKER_INPUT_BYTES:
        raise QualificationBlocked("production worker input exceeds its size cap")
    artifact_root.assert_path_identity()
    process_root.assert_path_identity()
    output: _AnchoredDirectory | None = None
    try:
        output = _open_child_directory(
            process_root,
            "output",
            "production output root",
            mode=0o700,
            create=False,
        )
        output_root = output.path
    finally:
        if output is not None:
            output.close()
    denied_name = f".w3-production-denied-{process_root.name}"
    denied_write = artifact_root.path / denied_name
    if _entry_exists_at(artifact_root, denied_name):
        raise QualificationBlocked("production external-write canary already exists")
    worker = source_bundle / worker_relative
    launcher = _launcher_identity_v3()
    python_root = Path(launcher["python_executable"]).parent.parent.resolve(strict=True)
    environment = {
        "LANG": "C",
        "LC_ALL": "C",
        "W3_PRODUCTION_SOURCE_BUNDLE": str(source_bundle),
        "W3_PRODUCTION_DEPENDENCY_BUNDLE": str(dependency_bundle),
        "W3_PRODUCTION_WORKER": str(worker),
        "W3_PRODUCTION_PROCESS_ROOT": str(process_root.path),
        "W3_PRODUCTION_OUTPUT_ROOT": str(output_root),
        "W3_PRODUCTION_DENIED_WRITE": str(denied_write),
        "W3_PRODUCTION_DENIED_READ": str(authority_path),
        "W3_PRODUCTION_DENIED_SOURCE_WRITE": str(source_bundle / "bundle.json"),
        "W3_PRODUCTION_DENIED_DEPENDENCY_WRITE": str(dependency_bundle / "bundle.json"),
        "W3_PRODUCTION_FILE_LIMIT": str(MAX_WORKER_STDOUT_BYTES),
    }
    command = [
        launcher["sandbox_exec_path"],
        "-p",
        V3_OUTER_SANDBOX_POLICY_TEMPLATE,
        "-D",
        f"PROCESS_ROOT={process_root.path}",
        "-D",
        f"PYTHON_EXECUTABLE={launcher['python_executable']}",
        "-D",
        f"PYTHON_ROOT={python_root}",
        "-D",
        f"SOURCE_BUNDLE_ROOT={source_bundle}",
        "-D",
        f"DEPENDENCY_BUNDLE_ROOT={dependency_bundle}",
        launcher["python_executable"],
        "-I",
        "-S",
        "-B",
        "-c",
        _V3_CHILD_BOOTSTRAP,
    ]
    process: subprocess.Popen[bytes] | None = None
    supervision_complete = False
    supervision = _bridge_child_supervision("worker")
    stdout_descriptor = -1
    stderr_descriptor = -1
    try:
        stdout_descriptor = os.open(
            "stdout.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=process_root.descriptor,
        )
        stderr_descriptor = os.open(
            "stderr.txt",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=process_root.descriptor,
        )
        with (
            os.fdopen(stdout_descriptor, "wb") as stdout,
            os.fdopen(stderr_descriptor, "wb") as stderr,
        ):
            stdout_descriptor = -1
            stderr_descriptor = -1
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                cwd=source_bundle,
                env=environment,
                **supervision,
            )
            try:
                process.communicate(input=request_bytes, timeout=timeout_seconds)
            except subprocess.TimeoutExpired as error:
                _kill_and_reap_process_group(process)
                supervision_complete = True
                raise QualificationBlocked("production worker exceeded the timeout cap") from error
            returncode = process.returncode
            _kill_and_reap_process_group(process)
            supervision_complete = True
    except (OSError, subprocess.SubprocessError) as error:
        raise QualificationBlocked("production worker could not start") from error
    finally:
        cleanup_error: QualificationBlocked | None = None
        if process is not None and not supervision_complete:
            try:
                _kill_and_reap_process_group(process)
            except QualificationBlocked as error:
                cleanup_error = error
        if stdout_descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(stdout_descriptor)
        if stderr_descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(stderr_descriptor)
        if cleanup_error is not None:
            raise cleanup_error
    if _entry_exists_at(artifact_root, denied_name):
        raise QualificationBlocked("production sandbox allowed an external write")
    artifact_root.assert_path_identity()
    process_root.assert_path_identity()
    stdout_bytes = _read_regular_at(
        process_root.descriptor,
        "stdout.json",
        MAX_WORKER_STDOUT_BYTES,
        "worker stdout",
        mode=0o600,
    )
    stderr_bytes = _read_regular_at(
        process_root.descriptor,
        "stderr.txt",
        MAX_WORKER_STDERR_BYTES,
        "worker stderr",
        mode=0o600,
    )
    if stderr_bytes:
        raise QualificationBlocked("production worker emitted unregistered stderr")
    if returncode != 0:
        failure = _decode_json(stdout_bytes, "blocked production worker output")
        failure = _exact_keys(
            failure,
            {"schema_version", "protocol", "status", "failure"},
            "blocked production worker output",
        )
        typed = _exact_keys(failure["failure"], {"kind", "message"}, "worker failure")
        if failure["status"] != "blocked" or typed["kind"] not in {
            "worker-input",
            "worker-trust",
            "worker-execution",
        }:
            raise QualificationBlocked("production worker failed without a typed failure")
        raise QualificationBlocked(f"production worker {typed['kind']} failure: {typed['message']}")
    return stdout_bytes


def _capsule_envelope_from_result_v3(
    *,
    execution: dict[str, Any],
    result: Any,
    run_nonce: str,
    authority: dict[str, Any],
) -> dict[str, Any]:
    request = execution["request"]
    runtime_authority = _v3_runtime_authority(authority)
    runtime = runtime_authority["runtime_identity"]
    result = _exact_keys(result, RESULT_KEYS, "capsule runner result")
    ir_value = result["ir"].get("value") if isinstance(result.get("ir"), dict) else None
    evidence = {
        "input_sha256": canonical_hash(request),
        "diagnostics_sha256": canonical_hash(result["diagnostics"]),
        "ast_sha256": canonical_hash(result["ast"]["inventory"]),
        "ir_sha256": None if ir_value is None else canonical_hash(ir_value),
        "toolchain_revision": PINNED_METIS_REVISION,
        "toolchain_tree": PINNED_METIS_TREE,
        "runtime_sha256": canonical_hash(runtime),
        "runtime_identity": runtime,
        **runtime_authority["evidence_pins"],
        "metis_status": "",
    }
    oracle_envelope: dict[str, Any] = {
        "schema_version": 1,
        "result": result,
        "evidence": evidence,
    }
    oracle_envelope["evidence"]["envelope_sha256"] = canonical_hash(oracle_envelope)
    _verify_envelope(
        oracle_envelope,
        request,
        execution["expected_status"],
        runtime_authority,
    )
    execution_id = f"{execution['candidate_id']}.{execution['role']}"
    body = {
        "schema_version": 3,
        "protocol": "metis-runtime-capsule-v3",
        "execution_id": execution_id,
        "request_sha256": canonical_hash(request),
        "capsule_manifest_sha256": authority["capsule"]["manifest_sha256"],
        "execution_policy": _validated_capsule_execution_policy_v3(),
        "oracle_envelope": oracle_envelope,
    }
    return {**body, "run_nonce": run_nonce, "manifest_sha256": canonical_hash(body)}


def _validated_capsule_execution_policy_v3() -> dict[str, Any]:
    measured = {
        "sandbox_policy_sha256": (
            HASH_PREFIX
            + hashlib.sha256(V3_NODE_SANDBOX_POLICY_TEMPLATE.encode("utf-8")).hexdigest()
        ),
        "capsule_ancestor_slots": V3_CAPSULE_ANCESTOR_SLOTS,
        "runtime_ancestor_slots": V3_CAPSULE_ANCESTOR_SLOTS,
        "process_fork": "denied",
        "supervision": "node-session-group-leader",
        "loader_flags": list(V3_LOADER_FLAGS),
    }
    if measured != V3_CAPSULE_EXECUTION_POLICY:
        raise QualificationBlocked("capsule process policy bytes differ from runtime identity")
    return dict(measured)


def _capsule_ancestor_definitions(capsule: Path) -> dict[str, str]:
    return _root_ancestor_definitions(capsule, "CAPSULE")


def _runtime_ancestor_definitions(runtime_root: Path) -> dict[str, str]:
    return _root_ancestor_definitions(runtime_root, "RUNTIME")


def _root_ancestor_definitions(root: Path, prefix: str) -> dict[str, str]:
    root = _strict_canonical_path(
        root,
        f"{prefix.lower()} root for Node policy",
        must_exist=True,
        directory=True,
    )
    ancestors: list[Path] = []
    current = root.parent
    while current != current.parent:
        try:
            metadata = current.lstat()
        except OSError as error:
            raise QualificationBlocked("capsule ancestry is unavailable") from error
        if current.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            raise QualificationBlocked("capsule ancestry contains a non-directory or symlink")
        ancestors.append(current)
        current = current.parent
    if len(ancestors) > V3_CAPSULE_ANCESTOR_SLOTS:
        raise QualificationBlocked("capsule ancestry exceeds the Node policy slot cap")
    padded = [*ancestors, *([root] * (V3_CAPSULE_ANCESTOR_SLOTS - len(ancestors)))]
    return {f"{prefix}_ANCESTOR_{index:02d}": str(path) for index, path in enumerate(padded)}


def _validate_capsule_ancestor_definitions(capsule: Path, definitions: Any) -> None:
    expected = _capsule_ancestor_definitions(capsule)
    if not isinstance(definitions, dict) or definitions != expected:
        raise QualificationBlocked("capsule ancestor policy parameters drifted")


def _execute_capsule_node_streams_v3(
    *,
    command: list[str],
    tooling: Path,
    request_bytes: bytes,
    process_root: _AnchoredDirectory,
    runtime_root: _AnchoredDirectory,
    invocation: _AnchoredDirectory,
    execution_id: str,
    timeout_seconds: float,
) -> bytes:
    process: subprocess.Popen[bytes] | None = None
    supervision_complete = False
    supervision = _bridge_child_supervision(f"node:{execution_id}")
    stdout_descriptor = -1
    stderr_descriptor = -1
    try:
        process_root.assert_path_identity()
        runtime_root.assert_path_identity()
        invocation.assert_path_identity()
        stdout_descriptor = os.open(
            "stdout.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=invocation.descriptor,
        )
        stderr_descriptor = os.open(
            "stderr.txt",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=invocation.descriptor,
        )
        with (
            os.fdopen(stdout_descriptor, "wb") as stdout,
            os.fdopen(stderr_descriptor, "wb") as stderr,
        ):
            stdout_descriptor = -1
            stderr_descriptor = -1
            process = subprocess.Popen(
                command,
                cwd=tooling,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                env=_v3_capsule_process_environment(process_root.path),
                **supervision,
            )
            if os.getpgid(process.pid) != process.pid or os.getsid(process.pid) != process.pid:
                _kill_and_reap_process_group(process)
                supervision_complete = True
                raise QualificationBlocked("capsule Node is not its supervised session leader")
            if process.stdin is None:
                _kill_and_reap_process_group(process)
                supervision_complete = True
                raise QualificationBlocked("capsule Node stdin was not created")
            try:
                process.stdin.write(request_bytes)
                process.stdin.close()
            except (BrokenPipeError, OSError) as error:
                _kill_and_reap_process_group(process)
                supervision_complete = True
                raise QualificationBlocked("capsule Node rejected its canonical request") from error
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    _kill_and_reap_process_group(process)
                    supervision_complete = True
                    raise QualificationBlocked("capsule Node exceeded the timeout cap")
                if os.fstat(stdout.fileno()).st_size > MAX_WORKER_STDOUT_BYTES:
                    _kill_and_reap_process_group(process)
                    supervision_complete = True
                    raise QualificationBlocked("capsule Node stdout exceeded its cap")
                if os.fstat(stderr.fileno()).st_size > MAX_WORKER_STDERR_BYTES:
                    _kill_and_reap_process_group(process)
                    supervision_complete = True
                    raise QualificationBlocked("capsule Node stderr exceeded its cap")
                time.sleep(0.01)
            returncode = process.returncode
            _kill_and_reap_process_group(process)
            supervision_complete = True
    except QualificationBlocked:
        raise
    except (OSError, subprocess.SubprocessError) as error:
        if process is not None:
            with contextlib.suppress(QualificationBlocked):
                _kill_and_reap_process_group(process)
        raise QualificationBlocked("capsule Node could not start") from error
    finally:
        cleanup_error: QualificationBlocked | None = None
        if process is not None and not supervision_complete:
            try:
                _kill_and_reap_process_group(process)
            except QualificationBlocked as error:
                cleanup_error = error
        if stdout_descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(stdout_descriptor)
        if stderr_descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(stderr_descriptor)
        if cleanup_error is not None:
            raise cleanup_error
    stdout_bytes = _read_regular_at(
        invocation.descriptor,
        "stdout.json",
        MAX_WORKER_STDOUT_BYTES,
        "capsule Node stdout",
        mode=0o600,
    )
    stderr_bytes = _read_regular_at(
        invocation.descriptor,
        "stderr.txt",
        MAX_WORKER_STDERR_BYTES,
        "capsule Node stderr",
        mode=0o600,
    )
    process_root.assert_path_identity()
    runtime_root.assert_path_identity()
    invocation.assert_path_identity()
    if returncode != 0 or stderr_bytes:
        raise QualificationBlocked("capsule Node failed or emitted unregistered stderr")
    return stdout_bytes


def _run_capsule_node_v3(
    *,
    execution: dict[str, Any],
    capsule: Path,
    node: Path,
    runtime_root: _AnchoredDirectory,
    process_root: _AnchoredDirectory,
    run_nonce: str,
    timeout_seconds: float,
    authority: dict[str, Any],
) -> dict[str, Any]:
    capsule_descriptor = authority["capsule"]
    loader = _source_file(
        capsule,
        _safe_relative_path(capsule_descriptor["loader"]["path"], "capsule loader path"),
        "capsule loader",
    )
    runner = _source_file(
        capsule,
        _safe_relative_path(capsule_descriptor["runner"]["path"], "capsule runner path"),
        "capsule runner",
    )
    tooling = capsule / "tooling"
    if tooling.is_symlink() or not tooling.is_dir():
        raise QualificationBlocked("capsule tooling directory is unavailable")
    execution_id = f"{execution['candidate_id']}.{execution['role']}"
    runtime = _v3_runtime_authority(authority)["runtime_identity"]
    ancestor_definitions = _capsule_ancestor_definitions(capsule)
    _validate_capsule_ancestor_definitions(capsule, ancestor_definitions)
    runtime_ancestors = _runtime_ancestor_definitions(runtime_root.path)
    if runtime_ancestors != _runtime_ancestor_definitions(runtime_root.path):
        raise QualificationBlocked("runtime ancestor policy parameters drifted")
    ancestor_arguments = [
        argument
        for name, value in {**ancestor_definitions, **runtime_ancestors}.items()
        for argument in ("-D", f"{name}={value}")
    ]

    def raw_hash(value: str) -> str:
        if not _valid_hash(value):
            raise QualificationBlocked("capsule execution pin is invalid")
        return value[len(HASH_PREFIX) :]

    snapshot = f"snapshot://{PINNED_METIS_REVISION}/{PINNED_METIS_TREE}"
    node_command = [
        str(node),
        *V3_LOADER_FLAGS,
        str(loader),
        str(runner),
        "--metis-root",
        str(capsule),
        "--metis-revision",
        PINNED_METIS_REVISION,
        "--metis-tree",
        PINNED_METIS_TREE,
        "--loader-path",
        str(loader),
        "--loader-sha256",
        raw_hash(capsule_descriptor["loader"]["sha256"]),
        "--runtime-loader-flags",
        json.dumps(list(V3_LOADER_FLAGS), separators=(",", ":")),
        "--runtime-node-path",
        runtime["node_path"],
        "--node-actual-path",
        str(node),
        "--runtime-loader-path",
        runtime["loader_path"],
        "--runtime-runner-path",
        runtime["runner_path"],
        "--runner-actual-path",
        str(runner),
        "--snapshot-identity",
        snapshot,
        "--node-modules-sha256",
        raw_hash(capsule_descriptor["tooling"]["node_modules_sha256"]),
        "--runner-sha256",
        raw_hash(capsule_descriptor["runner"]["sha256"]),
        "--node-binary-sha256",
        raw_hash(authority["runtime"]["node"]["sha256"]),
        "--oracle-policy-version",
        runtime["oracle_policy_version"],
        "--oracle-policy-sha256",
        raw_hash(runtime["oracle_policy_sha256"]),
        "--execution-policy-sha256",
        raw_hash(runtime["execution_policy_sha256"]),
        "--tooling-package-sha256",
        raw_hash(capsule_descriptor["tooling"]["package_sha256"]),
        "--tooling-lock-sha256",
        raw_hash(capsule_descriptor["tooling"]["lock_sha256"]),
    ]
    command = [
        str(SANDBOX_EXEC_PATH),
        "-p",
        V3_NODE_SANDBOX_POLICY_TEMPLATE,
        "-D",
        f"PROCESS_ROOT={process_root.path}",
        "-D",
        f"NODE_EXECUTABLE={node}",
        "-D",
        f"RUNTIME_ROOT={runtime_root.path}",
        "-D",
        f"CAPSULE_ROOT={capsule}",
        *ancestor_arguments,
        *node_command,
    ]
    request_bytes = canonical_json_bytes(execution["request"])
    namespace: _AnchoredDirectory | None = None
    invocation: _AnchoredDirectory | None = None
    try:
        namespace = _open_child_directory(
            process_root,
            "node-invocations",
            "capsule Node invocation namespace",
            mode=0o700,
            create=True,
            exist_ok=True,
        )
        invocation = _open_child_directory(
            namespace,
            execution_id,
            "capsule Node invocation",
            mode=0o700,
            create=True,
        )
        process_root.assert_path_identity()
        namespace.assert_path_identity()
        invocation.assert_path_identity()
        stdout_bytes = _execute_capsule_node_streams_v3(
            command=command,
            tooling=tooling,
            request_bytes=request_bytes,
            process_root=process_root,
            runtime_root=runtime_root,
            invocation=invocation,
            execution_id=execution_id,
            timeout_seconds=timeout_seconds,
        )
        result = _decode_json(stdout_bytes, "capsule Node stdout", require_canonical=True)
        envelope = _capsule_envelope_from_result_v3(
            execution=execution,
            result=result,
            run_nonce=run_nonce,
            authority=authority,
        )
        return envelope
    finally:
        if invocation is not None:
            invocation.close()
        if namespace is not None:
            namespace.close()


def _run_capsule_roster_v3(
    *,
    executions: list[dict[str, Any]],
    capsule: Path,
    node: Path,
    runtime_root: _AnchoredDirectory,
    process_root: _AnchoredDirectory,
    run_nonce: str,
    timeout_seconds: float,
    authority: dict[str, Any],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for execution in executions:
        envelope = _run_capsule_node_v3(
            execution=execution,
            capsule=capsule,
            node=node,
            runtime_root=runtime_root,
            process_root=process_root,
            run_nonce=run_nonce,
            timeout_seconds=timeout_seconds,
            authority=authority,
        )
        prepared.append({**execution, "capsule_envelope": envelope})
    return prepared


def _json_diff_paths(left: Any, right: Any, path: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(_json_diff_paths(left[key], right[key], child))
        return paths
    if isinstance(left, list) and isinstance(right, list):
        paths = []
        for index in range(max(len(left), len(right))):
            child = f"{path}[{index}]"
            if index >= len(left) or index >= len(right):
                paths.append(child)
            else:
                paths.extend(_json_diff_paths(left[index], right[index], child))
        return paths
    return [] if left == right else [path]


def _verify_envelope(
    envelope: Any,
    request: dict[str, Any],
    expected_status: str,
    authority: dict[str, Any],
) -> dict[str, Any]:
    envelope = _exact_keys(envelope, {"schema_version", "result", "evidence"}, "envelope")
    _exact_int(envelope["schema_version"], 1, "envelope schema version")
    result = _exact_keys(envelope["result"], RESULT_KEYS, "Oracle result")
    evidence = _exact_keys(envelope["evidence"], EVIDENCE_KEYS, "Oracle evidence")
    _exact_int(result["schema_version"], 1, "Oracle result schema version")
    if result["status"] != expected_status:
        raise QualificationBlocked("Oracle result status does not match its role")
    if evidence["input_sha256"] != canonical_hash(request):
        raise QualificationBlocked("Oracle input hash differs from the reconstructed request")
    if (
        evidence["toolchain_revision"] != authority["toolchain"]["revision"]
        or evidence["toolchain_tree"] != authority["toolchain"]["tree"]
        or result["toolchain"] != authority["toolchain"]
        or result["runtime"] != authority["runtime_identity"]
        or evidence["runtime_identity"] != authority["runtime_identity"]
        or evidence["runtime_sha256"] != canonical_hash(authority["runtime_identity"])
    ):
        raise QualificationBlocked("Oracle toolchain/runtime differs from authority")
    if any(evidence[key] != value for key, value in authority["evidence_pins"].items()):
        raise QualificationBlocked("Oracle evidence differs from its registered pins")
    diagnostics = _validate_diagnostics(
        result["diagnostics"], "Oracle diagnostics", expected_filename=request["filename"]
    )
    ast = result["ast"]
    ir = result["ir"]
    if (
        not isinstance(ast, dict)
        or set(ast) != {"inventory", "signature"}
        or not isinstance(ast["inventory"], dict)
        or not isinstance(ir, dict)
        or set(ir) != {"value", "signature"}
    ):
        raise QualificationBlocked("Oracle result omits typed diagnostic/AST/IR evidence")
    expected_ir_hash = None if ir["value"] is None else canonical_hash(ir["value"])
    if (
        evidence["diagnostics_sha256"] != canonical_hash(diagnostics)
        or ast["signature"] != canonical_hash(ast["inventory"])
        or evidence["ast_sha256"] != ast["signature"]
        or ir["signature"] != expected_ir_hash
        or evidence["ir_sha256"] != expected_ir_hash
        or evidence["metis_status_sha256"] != canonical_hash(evidence["metis_status"])
        or not isinstance(evidence["metis_status"], str)
    ):
        raise QualificationBlocked("Oracle evidence hashes do not match exact result values")
    unsigned = _decode_json(canonical_json_bytes(envelope), "Oracle envelope copy")
    stored = unsigned["evidence"].pop("envelope_sha256")
    if stored != canonical_hash(unsigned):
        raise QualificationBlocked("Oracle envelope hash does not match exact contents")
    endpoint = result["endpoint"]
    if not isinstance(endpoint, dict) or set(endpoint) != {"name", "count"}:
        raise QualificationBlocked("Oracle endpoint evidence is malformed")
    if expected_status == "ok":
        validation_errors = [
            item
            for item in diagnostics["validation"]
            if isinstance(item, dict) and item.get("severity") == 1
        ]
        if (
            result["failure"] is not None
            or diagnostics["parser"]
            or diagnostics["link"]
            or validation_errors
            or not isinstance(ir["value"], dict)
            or not isinstance(endpoint["name"], str)
            or not endpoint["name"]
        ):
            raise QualificationBlocked("Oracle ok result is logically inconsistent")
        _exact_int(endpoint["count"], 1, "Oracle ok endpoint count")
    else:
        _exact_int(endpoint["count"], 0, "Oracle invalid endpoint count")
        failure = _validate_failure(result["failure"], "Oracle failure")
        if (
            endpoint["name"] is not None
            or ir["value"] is not None
            or failure["kind"] not in {"parse", "link", "validation"}
        ):
            raise QualificationBlocked("Oracle invalid result is logically inconsistent")
    return result


def _verify_semantics(
    candidates: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    results: dict[tuple[str, str], dict[str, Any]],
) -> None:
    for candidate_id, candidate in candidates.items():
        family = candidate["family"]
        truth = specs[candidate_id]["semantic_spec"]["truth"]
        endpoint = truth["expected_endpoint"]
        if family == "F-1":
            result = results[(candidate_id, "author")]
            matched = (
                candidate["request"] == truth["request_exact"]
                and all(
                    fragment in candidate["target_source"]
                    for fragment in truth["required_source_fragments"]
                )
                and result["status"] == "ok"
                and result["endpoint"]["name"] == endpoint
                and result["ir"]["value"] == truth["expected_ir"]
            )
        elif family == "F-2":
            before = candidate["before_source"]
            after = candidate["after_source"]
            before_result = results[(candidate_id, "before")]
            after_result = results[(candidate_id, "after")]
            exact_edit = before.count(truth["old_text"]) == truth[
                "occurrences"
            ] and after == before.replace(
                truth["old_text"], truth["new_text"], truth["occurrences"]
            )
            expected_delta = {
                "replace": {"old_text": truth["old_text"], "new_text": truth["new_text"]}
            }
            before_ir = before_result["ir"]["value"]
            after_ir = after_result["ir"]["value"]
            matched = (
                exact_edit
                and candidate["expected_delta"] == expected_delta
                and before_result["status"] == after_result["status"] == "ok"
                and before_result["endpoint"]["name"] == endpoint
                and after_result["endpoint"]["name"] == endpoint
                and before_ir == truth["expected_before_ir"]
                and after_ir == truth["expected_after_ir"]
                and _json_diff_paths(before_ir, after_ir) == truth["expected_changed_paths"]
            )
        else:
            mutated = results[(candidate_id, "mutated")]
            fixed = results[(candidate_id, "fixed")]
            expected_diagnostic = {
                "failure_kind": truth["expected_failure_kind"],
                "diagnostic_present": truth["expected_diagnostic_present"],
            }
            expected_mutation = {"operation": "remove", "fragment": truth["repair_fragment"]}
            exact_mutation = candidate["fixed_source"].count(
                truth["repair_fragment"]
            ) == 1 and candidate["mutated_source"] == candidate["fixed_source"].replace(
                truth["repair_fragment"], "", 1
            )
            matched = (
                mutated["status"] == "invalid"
                and mutated["failure"] == truth["expected_failure"]
                and mutated["diagnostics"] == truth["expected_diagnostics"]
                and fixed["status"] == "ok"
                and fixed["endpoint"]["name"] == endpoint
                and fixed["ir"]["value"] == truth["expected_fixed_ir"]
                and candidate["expected_diagnostic"] == expected_diagnostic
                and candidate["mutation_spec"] == expected_mutation
                and exact_mutation
            )
        if not matched:
            raise QualificationBlocked(f"candidate {candidate_id} fails exact registered truth")


def _verify_worker_output(
    stdout_bytes: bytes,
    output_root: _AnchoredDirectory,
    request: dict[str, Any],
    request_bytes: bytes,
    authority: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    output = _decode_json(stdout_bytes, "worker stdout", require_canonical=True)
    output_keys = {
        "schema_version",
        "protocol",
        "authority_manifest_sha256",
        "bundle_sha256",
        "input_sha256",
        "status",
        "matched",
        "executions",
        "counts",
        "roles",
        "run_sha256",
    }
    output = _exact_keys(output, output_keys, "worker output")
    _exact_int(output["schema_version"], 1, "worker output schema version")
    if (
        output["protocol"] != PROTOCOL
        or output["status"] != "completed"
        or output["authority_manifest_sha256"] != request["authority_manifest_sha256"]
        or output["bundle_sha256"] != request["bundle_sha256"]
        or output["input_sha256"] != _bytes_hash(request_bytes)
    ):
        raise QualificationBlocked("worker output is not bound to its canonical input")
    if type(output["matched"]) is not bool:
        raise QualificationBlocked("worker matched field must be a strict boolean")
    run_body = {key: item for key, item in output.items() if key != "run_sha256"}
    if output["run_sha256"] != canonical_hash(run_body):
        raise QualificationBlocked("worker run hash does not match exact output")
    executions = output["executions"]
    if not isinstance(executions, list) or len(executions) != 5:
        raise QualificationBlocked("worker execution roster is not exact")
    expected_by_key = {(item["candidate_id"], item["role"]): item for item in request["executions"]}
    seen: set[tuple[str, str]] = set()
    results: dict[tuple[str, str], dict[str, Any]] = {}
    verified: list[dict[str, Any]] = []
    artifact_names: set[str] = set()
    artifact_bytes: dict[str, bytes] = {}
    output_root.assert_path_identity()
    for index, item in enumerate(executions):
        keys = {
            "candidate_id",
            "family",
            "role",
            "request",
            "request_sha256",
            "envelope",
            "envelope_sha256",
            "result_sha256",
            "artifact_path",
            "artifact_sha256",
        }
        item = _exact_keys(item, keys, f"worker execution {index}")
        if (
            not isinstance(item["candidate_id"], str)
            or CANDIDATE_ID_PATTERN.fullmatch(item["candidate_id"]) is None
            or item["family"] not in ROLE_CONTRACT
            or not isinstance(item["role"], str)
        ):
            raise QualificationBlocked("worker execution identity is invalid")
        key = (item["candidate_id"], item["role"])
        if key in seen or key not in expected_by_key:
            raise QualificationBlocked("worker returned a duplicate or mixed-role execution")
        expected = expected_by_key[key]
        if item["family"] != expected["family"] or item["request"] != expected["request"]:
            raise QualificationBlocked("worker execution differs from reconstructed role/request")
        if item["request_sha256"] != canonical_hash(expected["request"]):
            raise QualificationBlocked("worker request hash is invalid")
        result = _verify_envelope(
            item["envelope"], expected["request"], expected["expected_status"], authority
        )
        if item["envelope_sha256"] != canonical_hash(item["envelope"]) or item[
            "result_sha256"
        ] != canonical_hash(result):
            raise QualificationBlocked("worker envelope/result hash is invalid")
        relative = _safe_relative_path(item["artifact_path"], "worker artifact path")
        if (
            relative.as_posix() != item["artifact_path"]
            or ARTIFACT_PATH_PATTERN.fullmatch(item["artifact_path"]) is None
            or relative.parts[0] != "artifacts"
            or relative.as_posix() in artifact_names
        ):
            raise QualificationBlocked("worker artifact path is outside the registered namespace")
        artifact_names.add(relative.as_posix())
        raw = _read_regular_relative(
            output_root.descriptor,
            relative,
            MAX_ARTIFACT_BYTES,
            "worker artifact",
        )
        if raw != canonical_json_bytes(item["envelope"]):
            raise QualificationBlocked("worker artifact bytes differ from the envelope")
        if item["artifact_sha256"] != _bytes_hash(raw):
            raise QualificationBlocked("worker artifact hash is invalid")
        artifact_bytes[relative.as_posix()] = raw
        seen.add(key)
        results[key] = result
        verified.append(
            {
                "candidate_id": key[0],
                "family": item["family"],
                "role": key[1],
                "request_sha256": item["request_sha256"],
                "envelope_sha256": item["envelope_sha256"],
                "result_sha256": item["result_sha256"],
                "artifact_path": relative.as_posix(),
                "artifact_sha256": item["artifact_sha256"],
            }
        )
    if seen != set(expected_by_key):
        raise QualificationBlocked("worker execution roster has gaps")
    role_counts = dict(sorted(Counter(role for _, role in seen).items()))
    counts = {
        "candidates": len({candidate_id for candidate_id, _ in seen}),
        "executions": len(seen),
        "distinct": len(seen),
        "gaps": len(set(expected_by_key) - seen),
    }
    _exact_count_map(output["roles"], EXPECTED_ROLE_COUNTS, "worker role counts")
    _exact_count_map(
        output["counts"],
        {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0},
        "worker counts",
    )
    if output["roles"] != role_counts or output["counts"] != counts:
        raise QualificationBlocked("worker role/count claims differ from recomputed values")
    if counts != {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0}:
        raise QualificationBlocked("recomputed qualification denominator is not exact")
    _verify_semantics(candidates, specs, results)
    observed = _snapshot_qualification_descriptor(
        output_root.descriptor,
        artifact_names,
        immutable=False,
    )
    output_root.assert_path_identity()
    if observed != artifact_bytes:
        raise QualificationBlocked("worker output root contains unregistered files")
    return {"counts": counts, "roles": role_counts}, sorted(
        verified, key=lambda item: (item["candidate_id"], item["role"])
    )


def _v3_runtime_authority(authority: dict[str, Any]) -> dict[str, Any]:
    capsule = authority["capsule"]
    tooling = capsule["tooling"]
    snapshot = f"snapshot://{PINNED_METIS_REVISION}/{PINNED_METIS_TREE}"
    runtime = {
        "node": PINNED_NODE_VERSION,
        "node_path": f"node://{PINNED_NODE_VERSION}",
        "loader_path": f"{snapshot}/.metis-oracle/native_ts_loader.mjs",
        "loader_sha256": capsule["loader"]["sha256"],
        "loader_flags": list(V3_LOADER_FLAGS),
        "runner_path": f"{snapshot}/.metis-oracle/runner.ts",
        "snapshot_revision": PINNED_METIS_REVISION,
        "snapshot_tree": PINNED_METIS_TREE,
        "tooling_package_sha256": tooling["package_sha256"],
        "tooling_lock_sha256": tooling["lock_sha256"],
        "node_modules_sha256": tooling["node_modules_sha256"],
        "node_binary_sha256": authority["runtime"]["node"]["sha256"],
        "sandbox_exec_path": "sandbox-exec:///usr/bin/sandbox-exec",
        "oracle_policy_version": "2",
        "oracle_policy_sha256": (
            "sha256:deb8f45c9dfc2f336dbfb6f69a13e599a51929864ede8229969fa7f6e03f40aa"
        ),
        "execution_policy_sha256": V3_NODE_SANDBOX_POLICY_TEMPLATE_SHA256,
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
            "oracle_policy_sha256": runtime["oracle_policy_sha256"],
            "execution_policy_sha256": runtime["execution_policy_sha256"],
            "metis_status_sha256": canonical_hash(""),
        },
    }


def _verify_capsule_envelope_v3(
    value: Any,
    *,
    request: dict[str, Any],
    run_nonce: str,
    expected_status: str,
    authority: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    envelope = _exact_keys(
        value,
        {
            "schema_version",
            "protocol",
            "execution_id",
            "run_nonce",
            "request_sha256",
            "capsule_manifest_sha256",
            "execution_policy",
            "oracle_envelope",
            "manifest_sha256",
        },
        "capsule Oracle envelope",
    )
    _exact_int(envelope["schema_version"], 3, "capsule envelope schema version")
    if (
        envelope["protocol"] != "metis-runtime-capsule-v3"
        or not isinstance(envelope["execution_id"], str)
        or CANDIDATE_ID_PATTERN.fullmatch(envelope["execution_id"]) is None
        or envelope["run_nonce"] != run_nonce
        or envelope["request_sha256"] != canonical_hash(request)
        or envelope["capsule_manifest_sha256"] != authority["capsule"]["manifest_sha256"]
        or envelope["execution_policy"] != _validated_capsule_execution_policy_v3()
    ):
        raise QualificationBlocked("capsule envelope is not bound to its request and capsule")
    normalized = {key: item for key, item in envelope.items() if key != "run_nonce"}
    body = {key: item for key, item in normalized.items() if key != "manifest_sha256"}
    if envelope["manifest_sha256"] != canonical_hash(body):
        raise QualificationBlocked("capsule envelope digest is invalid")
    result = _verify_envelope(
        envelope["oracle_envelope"],
        request,
        expected_status,
        _v3_runtime_authority(authority),
    )
    return normalized, result


def _verify_worker_output_v3(
    stdout_bytes: bytes,
    output_root: _AnchoredDirectory,
    request: dict[str, Any],
    authority: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], str, bytes]:
    output = _decode_json(stdout_bytes, "production worker stdout", require_canonical=True)
    output = _exact_keys(
        output,
        {
            "schema_version",
            "protocol",
            "status",
            "authority_manifest_sha256",
            "run_nonce",
            "counts",
            "roles",
            "executions",
            "manifest_sha256",
        },
        "production worker output",
    )
    _exact_int(output["schema_version"], 3, "production worker schema version")
    if (
        output["protocol"] != V3_PROTOCOL
        or output["status"] != "completed"
        or output["authority_manifest_sha256"] != request["authority_manifest_sha256"]
        or output["run_nonce"] != request["run_nonce"]
    ):
        raise QualificationBlocked("production worker output is not bound to its input")
    run_body = {
        key: item for key, item in output.items() if key not in {"run_nonce", "manifest_sha256"}
    }
    if output["manifest_sha256"] != canonical_hash(run_body):
        raise QualificationBlocked("production worker output digest is invalid")
    rows = output["executions"]
    if not isinstance(rows, list) or len(rows) != 5:
        raise QualificationBlocked("production worker execution roster is not exact")
    expected_by_key = {(item["candidate_id"], item["role"]): item for item in request["executions"]}
    seen: set[tuple[str, str]] = set()
    results: dict[tuple[str, str], dict[str, Any]] = {}
    verified: list[dict[str, Any]] = []
    artifact_paths: set[str] = set()
    normalized_artifacts: dict[str, bytes] = {}
    output_root.assert_path_identity()
    for index, row in enumerate(rows):
        row = _exact_keys(
            row,
            {
                "candidate_id",
                "family",
                "role",
                "expected_status",
                "request",
                "request_sha256",
                "capsule_envelope",
                "capsule_envelope_sha256",
                "oracle_envelope_sha256",
                "result_sha256",
                "artifact_path",
                "artifact_sha256",
                "normalized_artifact_sha256",
            },
            f"production worker execution {index}",
        )
        key = (row["candidate_id"], row["role"])
        expected = expected_by_key.get(key)
        if (
            expected is None
            or key in seen
            or row["family"] != expected["family"]
            or row["expected_status"] != expected["expected_status"]
            or row["request"] != expected["request"]
            or row["request_sha256"] != canonical_hash(expected["request"])
        ):
            raise QualificationBlocked("production worker execution identity/request drifted")
        expected_execution_id = f"{row['candidate_id']}.{row['role']}"
        if row["capsule_envelope"].get("execution_id") != expected_execution_id:
            raise QualificationBlocked("capsule execution id differs from candidate role")
        normalized, result = _verify_capsule_envelope_v3(
            row["capsule_envelope"],
            request=expected["request"],
            run_nonce=request["run_nonce"],
            expected_status=expected["expected_status"],
            authority=authority,
        )
        if (
            row["capsule_envelope_sha256"] != canonical_hash(normalized)
            or row["oracle_envelope_sha256"]
            != canonical_hash(row["capsule_envelope"]["oracle_envelope"])
            or row["result_sha256"] != canonical_hash(result)
        ):
            raise QualificationBlocked("production worker envelope/result digest drifted")
        relative = _safe_relative_path(row["artifact_path"], "production artifact path")
        if (
            relative.as_posix() != row["artifact_path"]
            or ARTIFACT_PATH_PATTERN.fullmatch(row["artifact_path"]) is None
            or row["artifact_path"] in artifact_paths
        ):
            raise QualificationBlocked("production artifact path is invalid")
        raw = _read_regular_relative(
            output_root.descriptor,
            relative,
            MAX_ARTIFACT_BYTES,
            "production artifact",
        )
        if (
            raw != canonical_json_bytes(row["capsule_envelope"])
            or row["artifact_sha256"] != _bytes_hash(raw)
            or row["normalized_artifact_sha256"] != _bytes_hash(canonical_json_bytes(normalized))
        ):
            raise QualificationBlocked("production artifact bytes or digest drifted")
        normalized_bytes = canonical_json_bytes(normalized)
        _replace_regular_relative(
            output_root.descriptor,
            relative,
            normalized_bytes,
            "normalized artifact",
        )
        if (
            _read_regular_relative(
                output_root.descriptor,
                relative,
                MAX_ARTIFACT_BYTES,
                "normalized artifact",
            )
            != normalized_bytes
        ):
            raise QualificationBlocked("normalized artifact publication changed")
        seen.add(key)
        artifact_paths.add(row["artifact_path"])
        normalized_artifacts[row["artifact_path"]] = normalized_bytes
        results[key] = result
        verified.append(
            {
                "candidate_id": row["candidate_id"],
                "family": row["family"],
                "role": row["role"],
                "request_sha256": row["request_sha256"],
                "capsule_envelope_sha256": row["capsule_envelope_sha256"],
                "oracle_envelope_sha256": row["oracle_envelope_sha256"],
                "result_sha256": row["result_sha256"],
                "artifact_path": row["artifact_path"],
                "artifact_sha256": row["normalized_artifact_sha256"],
            }
        )
    if seen != set(expected_by_key):
        raise QualificationBlocked("production worker execution roster has gaps")
    counts = {
        "candidates": len({candidate for candidate, _ in seen}),
        "executions": len(seen),
        "distinct": len(seen),
        "gaps": len(set(expected_by_key) - seen),
    }
    roles = dict(sorted(Counter(role for _, role in seen).items()))
    _exact_count_map(
        output["counts"],
        {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0},
        "production worker counts",
    )
    _exact_count_map(output["roles"], EXPECTED_ROLE_COUNTS, "production worker roles")
    if (
        counts != {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0}
        or roles != EXPECTED_ROLE_COUNTS
        or output["counts"] != counts
        or output["roles"] != roles
    ):
        raise QualificationBlocked("production worker denominator or role claims are invalid")
    _verify_semantics(candidates, specs, results)
    observed = _snapshot_qualification_descriptor(
        output_root.descriptor,
        artifact_paths,
        immutable=False,
    )
    output_root.assert_path_identity()
    if observed != normalized_artifacts:
        raise QualificationBlocked("production output root contains unregistered content")
    normalized_summary = {
        "schema_version": 3,
        "protocol": V3_PROTOCOL,
        "status": "completed",
        "authority_manifest_sha256": output["authority_manifest_sha256"],
        "counts": counts,
        "roles": roles,
        "executions": verified,
    }
    return (
        {"counts": counts, "roles": roles},
        sorted(verified, key=lambda item: (item["candidate_id"], item["role"])),
        canonical_hash(normalized_summary),
        canonical_json_bytes(normalized_summary),
    )


def _expected_tree_directories(files: set[str]) -> set[str]:
    directories = {
        parent.as_posix()
        for name in files
        for parent in PurePosixPath(name).parents
        if parent.as_posix() != "."
    }
    return directories


def _validate_report(report: Any, launcher: dict[str, Any]) -> None:
    report = _exact_keys(report, QUALIFIED_V1_REPORT_KEYS, "qualification report")
    _exact_int(report["schema_version"], 1, "qualification report schema version")
    if (
        report["qualification_id"] != QUALIFICATION_ID
        or report["status"] != "qualified"
        or report["claim"] != CLAIM
        or report["launcher"] != launcher
        or report["stops"] != QUALIFICATION_STOPS
    ):
        raise QualificationBlocked("qualification report contract is invalid")
    for name in (
        "authority_manifest_sha256",
        "bundle_sha256",
        "semantic_registry_sha256",
        "candidate_manifest_sha256",
        "worker_input_sha256",
        "worker_output_sha256",
        "manifest_sha256",
    ):
        if not _valid_hash(report[name]):
            raise QualificationBlocked("qualification report contains an invalid digest")
    _exact_keys(report["launcher"], LAUNCHER_IDENTITY_KEYS, "report launcher identity")
    _exact_count_map(
        report["counts"],
        {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0},
        "report counts",
    )
    _exact_count_map(report["roles"], EXPECTED_ROLE_COUNTS, "report roles")
    _validate_cleanup(report["cleanup"], qualified=True, expected_kinds=("worker-process-root",))
    executions = report["executions"]
    if not isinstance(executions, list) or len(executions) != 5:
        raise QualificationBlocked("qualification report execution roster is invalid")
    seen: set[tuple[str, str]] = set()
    artifact_paths: set[str] = set()
    for index, execution in enumerate(executions):
        execution = _exact_keys(
            execution,
            {
                "candidate_id",
                "family",
                "role",
                "request_sha256",
                "envelope_sha256",
                "result_sha256",
                "artifact_path",
                "artifact_sha256",
            },
            f"qualification report execution {index}",
        )
        candidate_id = execution["candidate_id"]
        family = execution["family"]
        role = execution["role"]
        if (
            not isinstance(candidate_id, str)
            or CANDIDATE_ID_PATTERN.fullmatch(candidate_id) is None
            or family not in ROLE_CONTRACT
            or role not in {item[0] for item in ROLE_CONTRACT[family]}
            or (candidate_id, role) in seen
        ):
            raise QualificationBlocked("qualification report execution identity is invalid")
        artifact_path = execution["artifact_path"]
        if (
            not isinstance(artifact_path, str)
            or ARTIFACT_PATH_PATTERN.fullmatch(artifact_path) is None
            or _safe_relative_path(artifact_path, "report artifact path").as_posix()
            != artifact_path
            or artifact_path in artifact_paths
        ):
            raise QualificationBlocked("qualification report artifact path is invalid")
        if any(
            not _valid_hash(execution[name])
            for name in (
                "request_sha256",
                "envelope_sha256",
                "result_sha256",
                "artifact_sha256",
            )
        ):
            raise QualificationBlocked("qualification report execution digest is invalid")
        seen.add((candidate_id, role))
        artifact_paths.add(artifact_path)
    if len({candidate_id for candidate_id, _ in seen}) != 3:
        raise QualificationBlocked("qualification report candidate denominator is invalid")
    body = {key: item for key, item in report.items() if key != "manifest_sha256"}
    if report["manifest_sha256"] != canonical_hash(body):
        raise QualificationBlocked("qualification report digest is invalid")
    if len(canonical_json_bytes(report)) > MAX_REPORT_BYTES:
        raise QualificationBlocked("qualification report exceeds its size cap")


def _publish_qualification(
    artifact_root: _AnchoredDirectory,
    process_root: _AnchoredDirectory,
    report: dict[str, Any],
    registry: _RetainedRootRegistry | None = None,
) -> None:
    """Publish through retained directory FDs; never follow either root path."""

    artifact_files = {item["artifact_path"] for item in report["executions"]}
    expected_files = artifact_files | {"qualification.json"}
    input_is_sealed = process_root.mode == 0o555
    output: _AnchoredDirectory | None = None
    qualifications: _AnchoredDirectory | None = None
    target_name = report["manifest_sha256"][len(HASH_PREFIX) :]
    target: _AnchoredDirectory | None = None
    publication_token: int | None = None
    try:
        output = _open_child_directory(
            process_root,
            "output",
            "qualification output",
            mode=0o555 if input_is_sealed else 0o700,
            create=False,
        )
        qualifications = _open_child_directory(
            artifact_root,
            "qualifications",
            "qualification namespace",
            mode=0o700,
            create=True,
            exist_ok=True,
        )
        mutable_snapshot = _snapshot_qualification_descriptor(
            output.descriptor,
            artifact_files,
            immutable=input_is_sealed,
        )
        mutable_snapshot["qualification.json"] = canonical_json_bytes(report)
        if sum(len(raw) for raw in mutable_snapshot.values()) > MAX_PUBLISHED_BYTES:
            raise QualificationBlocked("qualification tree exceeds its aggregate size cap")

        try:
            target = _open_child_directory(
                qualifications,
                target_name,
                "existing qualification artifact",
                mode=0o555,
                create=False,
            )
        except QualificationBlocked as error:
            if not isinstance(error.__cause__, FileNotFoundError):
                raise
        if target is not None:
            existing = _snapshot_qualification_descriptor(
                target.descriptor,
                expected_files,
                immutable=True,
            )
            if existing != mutable_snapshot:
                raise QualificationBlocked("existing qualification artifact differs from replay")
            artifact_root.assert_path_identity()
            process_root.assert_path_identity()
            qualifications.assert_path_identity()
            target.assert_path_identity()
            return

        if registry is not None:
            publication_token = registry.intent(
                kind="qualification-publication-partial-root",
                logical_root="qualification-publication-partial",
                anchor="artifact-root",
                locator=f"qualifications/{target_name}",
            )
        try:
            target = _open_child_directory(
                qualifications,
                target_name,
                "qualification artifact",
                mode=0o700,
                create=True,
                created_callback=(
                    None
                    if registry is None or publication_token is None
                    else lambda: registry.mark_created(publication_token)
                ),
            )
            if registry is not None and publication_token is not None:
                registry.observe(publication_token, target)
        except QualificationBlocked as error:
            if not isinstance(error.__cause__, FileExistsError):
                if (
                    registry is not None
                    and publication_token is not None
                    and not registry.was_created(publication_token)
                ):
                    registry.cancel(publication_token)
                raise
            if registry is not None and publication_token is not None:
                registry.cancel(publication_token)
            target = _open_child_directory(
                qualifications,
                target_name,
                "raced qualification artifact",
                mode=0o555,
                create=False,
            )
            existing = _snapshot_qualification_descriptor(
                target.descriptor,
                expected_files,
                immutable=True,
            )
            if existing != mutable_snapshot:
                raise QualificationBlocked(
                    "raced qualification artifact differs from replay"
                ) from error
            artifact_root.assert_path_identity()
            process_root.assert_path_identity()
            qualifications.assert_path_identity()
            target.assert_path_identity()
            return

        try:
            for name, raw in sorted(mutable_snapshot.items()):
                _write_regular_relative(
                    target.descriptor,
                    _safe_relative_path(name, "qualification publication path"),
                    raw,
                    f"qualification publication file {name}",
                )
            staged = _snapshot_qualification_descriptor(
                target.descriptor,
                expected_files,
                immutable=False,
            )
            if staged != mutable_snapshot:
                raise QualificationBlocked("staged qualification artifact changed")
            _seal_directory_descriptor(target.descriptor)
            target.mode = 0o555
            published = _snapshot_qualification_descriptor(
                target.descriptor,
                expected_files,
                immutable=True,
            )
            if published != mutable_snapshot:
                raise QualificationBlocked("published qualification artifact changed")
            artifact_root.assert_path_identity()
            process_root.assert_path_identity()
            qualifications.assert_path_identity()
            target.assert_path_identity()
            target.owned_entry = False
            if registry is not None and publication_token is not None:
                registry.complete(publication_token)
        except Exception:
            target.close()
            target = None
            raise
    finally:
        if target is not None:
            target.close()
        if qualifications is not None:
            qualifications.close()
        if output is not None:
            output.close()


def _qualify_impl(
    *,
    authority_path: str | os.PathLike[str],
    authority_sha256: str,
    source_root: str | os.PathLike[str],
    artifact_root: str | os.PathLike[str],
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Run the bounded verifier once and return its canonical report object."""

    launcher_before = _launcher_identity()
    if type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise QualificationBlocked("timeout must be positive and within the registered cap")
    try:
        source = Path(source_root).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise QualificationBlocked("source root is unavailable") from error
    if not source.is_dir():
        raise QualificationBlocked("source root is not a directory")
    artifact = Path(artifact_root).absolute()
    try:
        artifact_resolved = artifact.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise QualificationBlocked("artifact root is invalid") from error
    if (
        artifact_resolved == source
        or source in artifact_resolved.parents
        or artifact_resolved in source.parents
    ):
        raise QualificationBlocked("artifact root must be outside the source/Git root")
    try:
        authority_file = Path(authority_path).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise QualificationBlocked("authority manifest is unavailable") from error
    if (
        authority_file in (source, artifact_resolved)
        or source in authority_file.parents
        or artifact_resolved in authority_file.parents
    ):
        raise QualificationBlocked("authority manifest must be external to source and artifacts")

    # All authority and source-byte checks occur before the artifact root is
    # created and, critically, before any child process exists.
    authority = _load_authority(authority_file, authority_sha256)
    material, contents = _read_bundle_sources(authority, source)
    candidates, specs, executions = _load_gate_inputs(authority, contents)

    registry = _RetainedRootRegistry()
    process_root: _AnchoredDirectory | None = None
    artifact_handle: _AnchoredDirectory | None = None
    try:
        artifact_handle = _open_or_create_secure_root(artifact_resolved, "artifact root")
        bundle, bundle_sha256, bundle_body = _materialize_bundle(
            artifact_handle, authority_sha256, material, contents
        )
        request = _worker_input(authority, authority_sha256, bundle_sha256, executions)
        request_bytes = canonical_json_bytes(request)
        stdout_bytes, process_root = _run_worker(
            bundle,
            authority["worker"]["path"],
            source,
            artifact_handle,
            request_bytes,
            float(timeout_seconds),
            registry,
        )
        process_root.assert_path_identity()
        output_root: _AnchoredDirectory | None = None
        try:
            output_root = _open_child_directory(
                process_root,
                "output",
                "worker output root",
                mode=0o700,
                create=False,
            )
            denominators, verified = _verify_worker_output(
                stdout_bytes,
                output_root,
                request,
                request_bytes,
                authority,
                candidates,
                specs,
            )
        finally:
            if output_root is not None:
                output_root.close()
        artifact_handle.assert_path_identity()
        bundles: _AnchoredDirectory | None = None
        bundle_handle: _AnchoredDirectory | None = None
        try:
            bundles = _open_child_directory(
                artifact_handle,
                "bundles",
                "bundle namespace",
                mode=0o700,
                create=False,
            )
            bundle_handle = _open_child_directory(
                bundles,
                bundle_sha256[len(HASH_PREFIX) :],
                "materialized bundle",
                mode=0o555,
                create=False,
            )
            _verify_materialized_bundle(bundle_handle, bundle_body, contents)
            artifact_handle.assert_path_identity()
        finally:
            if bundle_handle is not None:
                bundle_handle.close()
            if bundles is not None:
                bundles.close()
        launcher_after = _launcher_identity()
        if launcher_after != launcher_before or launcher_after != authority["launcher"]:
            raise QualificationBlocked("launcher identity changed during qualification")
        cleanup = registry.cleanup(qualified=True)
        report_body = {
            "schema_version": SCHEMA_VERSION,
            "qualification_id": QUALIFICATION_ID,
            "status": "qualified",
            "claim": CLAIM,
            "authority_manifest_sha256": authority_sha256,
            "bundle_sha256": bundle_sha256,
            "semantic_registry_sha256": authority["semantic_registry"]["manifest_sha256"],
            "candidate_manifest_sha256": authority["candidate_manifest"]["manifest_sha256"],
            "worker_input_sha256": _bytes_hash(request_bytes),
            "worker_output_sha256": _bytes_hash(stdout_bytes),
            "launcher": launcher_before,
            "counts": denominators["counts"],
            "roles": denominators["roles"],
            "executions": verified,
            "stops": list(QUALIFICATION_STOPS),
            "cleanup": cleanup,
        }
        report = {**report_body, "manifest_sha256": canonical_hash(report_body)}
        _validate_report(report, launcher_before)
        _publish_qualification(artifact_handle, process_root, report, registry)
        artifact_handle.assert_path_identity()
        return report
    except Exception as error:
        cleanup = registry.cleanup(qualified=False)
        _validate_cleanup(
            cleanup,
            qualified=False,
            blocked_prefixes=BLOCKED_V1_RETAINED_PREFIXES,
        )
        if isinstance(error, QualificationBlocked):
            error.cleanup = cleanup
            raise
        raise QualificationBlocked(
            "qualification failed after retained root creation", cleanup=cleanup
        ) from error
    finally:
        if process_root is not None:
            process_root.close()
        registry.close()
        if artifact_handle is not None:
            artifact_handle.close()


def _validate_report_v3(report: Any, launcher: dict[str, Any]) -> None:
    report = _exact_keys(
        report,
        QUALIFIED_V3_REPORT_KEYS,
        "production qualification report",
    )
    _exact_int(report["schema_version"], 3, "production report schema version")
    if (
        report["qualification_id"] != V3_QUALIFICATION_ID
        or report["qualification_kind"] != "production-capsule-v3"
        or report["status"] != "qualified"
        or report["claim"] != V3_CLAIM
        or report["ratification_evidence_sha256"] != V3_KIMI_REPORT_SHA256
        or report["project_revision"] != V3_PROJECT_SHA
        or report["candidate_manifest_sha256"] != V3_CANDIDATE_MANIFEST_SHA256
        or report["semantic_registry_sha256"] != V3_SEMANTIC_REGISTRY_SHA256
        or report["dependency_roster_sha256"] != V3_DEPENDENCY_ROSTER_SHA256
        or report["launcher"] != launcher
        or report["native_evidence"] != V3_NATIVE_EVIDENCE
        or report["non_claims"] != V3_NON_CLAIMS
    ):
        raise QualificationBlocked("production qualification report contract is invalid")
    for field in (
        "authority_manifest_sha256",
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
            raise QualificationBlocked("production qualification report has an invalid digest")
    _exact_count_map(
        report["counts"],
        {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0},
        "production report counts",
    )
    _exact_count_map(report["roles"], EXPECTED_ROLE_COUNTS, "production report roles")
    _validate_cleanup(
        report["cleanup"],
        qualified=True,
        expected_kinds=QUALIFIED_V3_RETAINED_KINDS,
    )
    rows = report["executions"]
    if not isinstance(rows, list) or len(rows) != 5:
        raise QualificationBlocked("production report execution roster is invalid")
    seen: set[tuple[str, str]] = set()
    paths: set[str] = set()
    for index, row in enumerate(rows):
        row = _exact_keys(
            row,
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
            f"production report execution {index}",
        )
        key = (row["candidate_id"], row["role"])
        if (
            not isinstance(row["candidate_id"], str)
            or CANDIDATE_ID_PATTERN.fullmatch(row["candidate_id"]) is None
            or row["family"] not in ROLE_CONTRACT
            or row["role"] not in {item[0] for item in ROLE_CONTRACT[row["family"]]}
            or key in seen
            or row["artifact_path"] in paths
            or ARTIFACT_PATH_PATTERN.fullmatch(row["artifact_path"] or "") is None
            or _safe_relative_path(row["artifact_path"], "report artifact").as_posix()
            != row["artifact_path"]
        ):
            raise QualificationBlocked("production report execution identity is invalid")
        if any(
            not _valid_hash(row[field])
            for field in (
                "request_sha256",
                "capsule_envelope_sha256",
                "oracle_envelope_sha256",
                "result_sha256",
                "artifact_sha256",
            )
        ):
            raise QualificationBlocked("production report execution digest is invalid")
        seen.add(key)
        paths.add(row["artifact_path"])
    if len({candidate for candidate, _ in seen}) != 3:
        raise QualificationBlocked("production report candidate denominator is invalid")
    body = {key: item for key, item in report.items() if key != "manifest_sha256"}
    if report["manifest_sha256"] != canonical_hash(body):
        raise QualificationBlocked("production qualification report digest is invalid")


def _resolve_external_root(value: str | os.PathLike[str], label: str) -> Path:
    return _strict_canonical_path(value, label, must_exist=True, directory=True)


def _assert_disjoint_roots(named: dict[str, Path]) -> None:
    items = list(named.items())
    for index, (left_name, left) in enumerate(items):
        for right_name, right in items[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise QualificationBlocked(f"{left_name} and {right_name} must be disjoint")


def _qualify_v3_impl(
    *,
    authority_path: str | os.PathLike[str],
    authority_sha256: str,
    source_bundle_root: str | os.PathLike[str],
    dependency_bundle_root: str | os.PathLike[str],
    capsule_root: str | os.PathLike[str],
    node_path: str | os.PathLike[str],
    artifact_root: str | os.PathLike[str],
    run_root: str | os.PathLike[str],
    run_nonce: str,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    launcher_before = _launcher_identity_v3()
    if type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise QualificationBlocked("production timeout is outside the registered cap")
    if not isinstance(run_nonce, str) or re.fullmatch(r"[0-9a-f]{64}", run_nonce) is None:
        raise QualificationBlocked("production run nonce must be exactly 32 random bytes in hex")
    authority_file = _strict_canonical_path(
        authority_path,
        "production authority",
        must_exist=True,
        directory=False,
    )
    authority = _load_authority_v3(authority_file, authority_sha256)

    source_bundle = _resolve_external_root(source_bundle_root, "source bundle root")
    dependency_bundle = _resolve_external_root(dependency_bundle_root, "dependency bundle root")
    capsule = _resolve_external_root(capsule_root, "capsule root")
    node_source = _strict_canonical_path(
        node_path, "registered Node source", must_exist=True, directory=False
    )
    artifact = _strict_canonical_path(
        artifact_root,
        "artifact root",
        must_exist=False,
        directory=True,
    )
    run = _strict_canonical_path(
        run_root,
        "run root",
        must_exist=False,
        directory=True,
    )
    _assert_disjoint_roots(
        {
            "authority": authority_file,
            "source bundle": source_bundle,
            "dependency bundle": dependency_bundle,
            "capsule": capsule,
            "registered Node source": node_source,
            "artifact root": artifact,
            "run root": run,
        }
    )
    source_bundle, source_contents = _verify_external_tree(
        source_bundle,
        authority["source_bundle"],
        manifest_name="bundle.json",
        label="source bundle",
    )
    dependency_bundle, dependency_contents = _verify_external_tree(
        dependency_bundle,
        authority["dependency_bundle"],
        manifest_name="bundle.json",
        label="dependency bundle",
    )
    capsule, capsule_contents = _verify_external_tree(
        capsule,
        authority["capsule"],
        manifest_name="capsule.json",
        label="runtime capsule",
    )
    gate_authority = {
        "candidate_manifest": authority["project"]["candidate_manifest"],
        "semantic_registry": authority["project"]["semantic_registry"],
        "toolchain": {
            "revision": PINNED_METIS_REVISION,
            "tree": PINNED_METIS_TREE,
            "language_version": "0.43",
        },
    }
    candidates, specs, executions = _load_gate_inputs(gate_authority, source_contents)
    registry = _RetainedRootRegistry()
    artifact_handle: _AnchoredDirectory | None = None
    run_handle: _AnchoredDirectory | None = None
    process_root: _AnchoredDirectory | None = None
    runtime_root: _AnchoredDirectory | None = None
    trusted_root: _AnchoredDirectory | None = None
    try:
        artifact_handle = _open_or_create_secure_root(artifact, "artifact root")
        run_handle = _open_or_create_secure_root(run, "run root")
        if artifact_handle is None or run_handle is None:
            raise QualificationBlocked("production roots could not be opened securely")
        process_root = _create_random_directory(
            run_handle,
            ".w3-production-",
            "production process root",
            registry=registry,
            kind="production-process-root",
            logical_root="process",
            anchor="run-root",
        )
        runtime_root = _create_random_directory(
            run_handle,
            ".w3-runtime-",
            "production runtime root",
            registry=registry,
            kind="production-runtime-root",
            logical_root="runtime",
            anchor="run-root",
        )
        trusted_root = _create_random_directory(
            run_handle,
            ".w3-trusted-",
            "production trusted root",
            registry=registry,
            kind="production-trusted-root",
            logical_root="trusted",
            anchor="run-root",
        )
        output: _AnchoredDirectory | None = None
        try:
            output = _open_child_directory(
                process_root,
                "output",
                "production output root",
                mode=0o700,
                create=True,
            )
            output.assert_path_identity()
        finally:
            if output is not None:
                output.close()
        artifact_handle.assert_path_identity()
        run_handle.assert_path_identity()
        process_root.assert_path_identity()
        runtime_root.assert_path_identity()
        trusted_root.assert_path_identity()
        retained_node = _materialize_runtime_node_v3(
            runtime_root,
            node_source,
            authority["runtime"]["node"],
        )
        source_preimage = _materialize_tree_preimage_v3(
            trusted_root,
            kind="source",
            descriptor=authority["source_bundle"],
            contents=source_contents,
            manifest_name="bundle.json",
            label="source bundle",
        )
        dependency_preimage = _materialize_tree_preimage_v3(
            trusted_root,
            kind="dependency",
            descriptor=authority["dependency_bundle"],
            contents=dependency_contents,
            manifest_name="bundle.json",
            label="dependency bundle",
        )
        capsule_preimage = _materialize_tree_preimage_v3(
            trusted_root,
            kind="capsule",
            descriptor=authority["capsule"],
            contents=capsule_contents,
            manifest_name="capsule.json",
            label="runtime capsule",
        )
        _seal_preimage_namespace_v3(trusted_root)
        trusted_root.assert_path_identity()
        supervised_executions = _run_capsule_roster_v3(
            executions=executions,
            capsule=capsule_preimage,
            node=retained_node,
            runtime_root=runtime_root,
            process_root=process_root,
            run_nonce=run_nonce,
            timeout_seconds=float(timeout_seconds),
            authority=authority,
        )
        worker_request = {
            "schema_version": 3,
            "protocol": V3_PROTOCOL,
            "authority_manifest_sha256": authority_sha256,
            "source_bundle_manifest_sha256": authority["source_bundle"]["manifest_sha256"],
            "dependency_bundle_manifest_sha256": authority["dependency_bundle"]["manifest_sha256"],
            "capsule_manifest_sha256": authority["capsule"]["manifest_sha256"],
            "candidate_manifest_sha256": V3_CANDIDATE_MANIFEST_SHA256,
            "semantic_registry_sha256": V3_SEMANTIC_REGISTRY_SHA256,
            "run_nonce": run_nonce,
            "expected": authority["expected"],
            "executions": supervised_executions,
        }
        request_bytes = canonical_json_bytes(worker_request)
        stdout_bytes = _run_worker_v3(
            source_bundle=source_preimage,
            dependency_bundle=dependency_preimage,
            worker_relative=authority["project"]["worker"]["path"],
            authority_path=authority_file,
            artifact_root=artifact_handle,
            process_root=process_root,
            request_bytes=request_bytes,
            timeout_seconds=float(timeout_seconds),
        )
        output_root: _AnchoredDirectory | None = None
        try:
            output_root = _open_child_directory(
                process_root,
                "output",
                "production output root",
                mode=0o700,
                create=False,
            )
            (
                denominators,
                verified,
                normalized_worker_sha256,
                normalized_worker_bytes,
            ) = _verify_worker_output_v3(
                stdout_bytes,
                output_root,
                worker_request,
                authority,
                candidates,
                specs,
            )
        finally:
            if output_root is not None:
                output_root.close()
        _canonicalize_owned_regular_at(
            process_root,
            "stdout.json",
            stdout_bytes,
            normalized_worker_bytes,
        )
        _verify_tree_preimage_at_v3(
            trusted_root,
            kind="source",
            descriptor=authority["source_bundle"],
            contents=source_contents,
            manifest_name="bundle.json",
            label="source bundle",
        )
        _verify_tree_preimage_at_v3(
            trusted_root,
            kind="dependency",
            descriptor=authority["dependency_bundle"],
            contents=dependency_contents,
            manifest_name="bundle.json",
            label="dependency bundle",
        )
        _verify_tree_preimage_at_v3(
            trusted_root,
            kind="capsule",
            descriptor=authority["capsule"],
            contents=capsule_contents,
            manifest_name="capsule.json",
            label="runtime capsule",
        )
        _verify_runtime_node_v3(runtime_root, authority["runtime"]["node"])
        launcher_after = _launcher_identity_v3()
        if launcher_after != launcher_before or launcher_after != authority["project"]["launcher"]:
            raise QualificationBlocked("production launcher changed during qualification")
        request_without_nonce = {
            key: item
            for key, item in worker_request.items()
            if key not in {"run_nonce", "executions"}
        }
        request_without_nonce["executions"] = [
            {
                **{key: item for key, item in execution.items() if key != "capsule_envelope"},
                "capsule_envelope": {
                    key: item
                    for key, item in execution["capsule_envelope"].items()
                    if key != "run_nonce"
                },
            }
            for execution in worker_request["executions"]
        ]
        cleanup = registry.cleanup(qualified=True)
        report_body = {
            "schema_version": 3,
            "qualification_id": V3_QUALIFICATION_ID,
            "qualification_kind": "production-capsule-v3",
            "status": "qualified",
            "claim": V3_CLAIM,
            "authority_manifest_sha256": authority_sha256,
            "ratification_evidence_sha256": V3_KIMI_REPORT_SHA256,
            "project_revision": V3_PROJECT_SHA,
            "source_bundle_manifest_sha256": authority["source_bundle"]["manifest_sha256"],
            "dependency_bundle_manifest_sha256": authority["dependency_bundle"]["manifest_sha256"],
            "dependency_roster_sha256": V3_DEPENDENCY_ROSTER_SHA256,
            "capsule_manifest_sha256": authority["capsule"]["manifest_sha256"],
            "candidate_manifest_sha256": V3_CANDIDATE_MANIFEST_SHA256,
            "semantic_registry_sha256": V3_SEMANTIC_REGISTRY_SHA256,
            "worker_input_sha256": canonical_hash(request_without_nonce),
            "worker_output_sha256": normalized_worker_sha256,
            "launcher": launcher_before,
            "counts": denominators["counts"],
            "roles": denominators["roles"],
            "executions": verified,
            "native_evidence": dict(V3_NATIVE_EVIDENCE),
            "non_claims": list(V3_NON_CLAIMS),
            "cleanup": cleanup,
        }
        report = {**report_body, "manifest_sha256": canonical_hash(report_body)}
        _validate_report_v3(report, launcher_before)
        _publish_qualification(artifact_handle, process_root, report, registry)
        artifact_handle.assert_path_identity()
        run_handle.assert_path_identity()
        return report
    except Exception as error:
        cleanup = registry.cleanup(qualified=False)
        _validate_cleanup(
            cleanup,
            qualified=False,
            blocked_prefixes=BLOCKED_V3_RETAINED_PREFIXES,
        )
        if isinstance(error, QualificationBlocked):
            error.cleanup = cleanup
            raise
        raise QualificationBlocked(
            "production qualification failed after retained root creation",
            cleanup=cleanup,
        ) from error
    finally:
        if process_root is not None:
            process_root.close()
        if runtime_root is not None:
            runtime_root.close()
        if trusted_root is not None:
            trusted_root.close()
        registry.close()
        if run_handle is not None:
            run_handle.close()
        if artifact_handle is not None:
            artifact_handle.close()


def qualify_v3(
    *,
    authority_path: str | os.PathLike[str],
    authority_sha256: str,
    source_bundle_root: str | os.PathLike[str],
    dependency_bundle_root: str | os.PathLike[str],
    capsule_root: str | os.PathLike[str],
    node_path: str | os.PathLike[str],
    artifact_root: str | os.PathLike[str],
    run_root: str | os.PathLike[str],
    run_nonce: str,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    try:
        _require_protected_execution_broker()
        _require_launcher_flags()
        return _qualify_v3_impl(
            authority_path=authority_path,
            authority_sha256=authority_sha256,
            source_bundle_root=source_bundle_root,
            dependency_bundle_root=dependency_bundle_root,
            capsule_root=capsule_root,
            node_path=node_path,
            artifact_root=artifact_root,
            run_root=run_root,
            run_nonce=run_nonce,
            timeout_seconds=timeout_seconds,
        )
    except QualificationBlocked as error:
        if error.cleanup is None:
            error.cleanup = _empty_cleanup()
        raise
    except Exception as error:
        raise QualificationBlocked(
            "malformed v3 input caused an internal rejection", cleanup=_empty_cleanup()
        ) from error


def qualify(
    *,
    authority_path: str | os.PathLike[str],
    authority_sha256: str,
    source_root: str | os.PathLike[str],
    artifact_root: str | os.PathLike[str],
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Fail closed, including for malformed nested input that raises unexpectedly."""

    try:
        _require_launcher_flags()
        return _qualify_impl(
            authority_path=authority_path,
            authority_sha256=authority_sha256,
            source_root=source_root,
            artifact_root=artifact_root,
            timeout_seconds=timeout_seconds,
        )
    except QualificationBlocked as error:
        if error.cleanup is None:
            error.cleanup = _empty_cleanup()
        raise
    except Exception as error:
        raise QualificationBlocked(
            "malformed input caused an internal verifier rejection", cleanup=_empty_cleanup()
        ) from error


def _validate_blocked_report(report: Any, *, production: bool) -> dict[str, Any]:
    expected_keys = BLOCKED_V3_REPORT_KEYS if production else BLOCKED_V1_REPORT_KEYS
    blocked = _exact_keys(report, expected_keys, "blocked qualification report")
    _exact_int(
        blocked["schema_version"],
        V3_SCHEMA_VERSION if production else SCHEMA_VERSION,
        "blocked qualification report schema version",
    )
    if (
        blocked["qualification_id"] != (V3_QUALIFICATION_ID if production else QUALIFICATION_ID)
        or blocked["status"] != "blocked"
        or blocked["claim"] != "no_qualification_claim"
        or not isinstance(blocked["reason"], str)
        or not blocked["reason"]
    ):
        raise QualificationBlocked("blocked qualification report contract is invalid")
    if production:
        if blocked["qualification_kind"] != "production-capsule-v3":
            raise QualificationBlocked("blocked production qualification kind is invalid")
        if blocked["native_evidence"] != V3_NATIVE_EVIDENCE:
            raise QualificationBlocked("blocked production native evidence binding drifted")
        blocked_prefixes = BLOCKED_V3_RETAINED_PREFIXES
    else:
        blocked_prefixes = BLOCKED_V1_RETAINED_PREFIXES
    _validate_cleanup(
        blocked["cleanup"],
        qualified=False,
        blocked_prefixes=blocked_prefixes,
    )
    return blocked


def _blocked(reason: str, cleanup: dict[str, Any] | None = None) -> dict[str, Any]:
    report = {
        "schema_version": SCHEMA_VERSION,
        "qualification_id": QUALIFICATION_ID,
        "status": "blocked",
        "claim": "no_qualification_claim",
        "reason": reason,
        "cleanup": _empty_cleanup() if cleanup is None else cleanup,
    }
    return _validate_blocked_report(report, production=False)


def _blocked_v3(reason: str, cleanup: dict[str, Any] | None = None) -> dict[str, Any]:
    report = {
        "schema_version": V3_SCHEMA_VERSION,
        "qualification_id": V3_QUALIFICATION_ID,
        "qualification_kind": "production-capsule-v3",
        "status": "blocked",
        "claim": "no_qualification_claim",
        "reason": reason,
        "native_evidence": dict(V3_NATIVE_EVIDENCE),
        "cleanup": _empty_cleanup() if cleanup is None else cleanup,
    }
    return _validate_blocked_report(report, production=True)


class _CanonicalArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise QualificationBlocked(f"invalid command line: {message}")


def _preclassify_cli_mode(argv: list[str]) -> tuple[str, int]:
    """Select the blocked schema without accepting malformed parser state."""

    values: list[str | None] = []
    for index, token in enumerate(argv):
        if token == "--mode":
            value = argv[index + 1] if index + 1 < len(argv) else None
            values.append(value)
        elif token.startswith("--mode="):
            values.append(token.partition("=")[2])
    mode = "production-capsule-v3" if "production-capsule-v3" in values else "fixture-v1"
    return mode, len(values)


def main(argv: list[str] | None = None) -> int:
    parser = _CanonicalArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--mode",
        choices=("fixture-v1", "production-capsule-v3"),
        default="fixture-v1",
    )
    parser.add_argument("--authority", required=True)
    parser.add_argument("--authority-sha256", required=True)
    parser.add_argument("--source-root")
    parser.add_argument("--source-bundle-root")
    parser.add_argument("--dependency-bundle-root")
    parser.add_argument("--capsule-root")
    parser.add_argument("--node-path")
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--run-root")
    parser.add_argument("--run-nonce")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    mode, mode_count = _preclassify_cli_mode(raw_arguments)
    try:
        _require_launcher_flags()
        if mode_count > 1:
            raise QualificationBlocked("invalid command line: --mode may appear at most once")
        arguments = parser.parse_args(raw_arguments)
        mode = arguments.mode
        if mode == "fixture-v1":
            if arguments.source_root is None:
                raise QualificationBlocked("fixture-v1 requires --source-root")
            if any(
                value is not None
                for value in (
                    arguments.source_bundle_root,
                    arguments.dependency_bundle_root,
                    arguments.capsule_root,
                    arguments.node_path,
                    arguments.run_root,
                    arguments.run_nonce,
                )
            ):
                raise QualificationBlocked("fixture-v1 rejects production-capsule arguments")
            report = qualify(
                authority_path=arguments.authority,
                authority_sha256=arguments.authority_sha256,
                source_root=arguments.source_root,
                artifact_root=arguments.artifact_root,
                timeout_seconds=arguments.timeout_seconds,
            )
        else:
            required = {
                "--source-bundle-root": arguments.source_bundle_root,
                "--dependency-bundle-root": arguments.dependency_bundle_root,
                "--capsule-root": arguments.capsule_root,
                "--node-path": arguments.node_path,
                "--run-root": arguments.run_root,
                "--run-nonce": arguments.run_nonce,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing or arguments.source_root is not None:
                raise QualificationBlocked(
                    "production-capsule-v3 arguments are invalid: " + ",".join(missing)
                )
            report = qualify_v3(
                authority_path=arguments.authority,
                authority_sha256=arguments.authority_sha256,
                source_bundle_root=arguments.source_bundle_root,
                dependency_bundle_root=arguments.dependency_bundle_root,
                capsule_root=arguments.capsule_root,
                node_path=arguments.node_path,
                artifact_root=arguments.artifact_root,
                run_root=arguments.run_root,
                run_nonce=arguments.run_nonce,
                timeout_seconds=arguments.timeout_seconds,
            )
    except QualificationBlocked as error:
        blocked = (
            _blocked_v3(str(error), error.cleanup)
            if mode == "production-capsule-v3"
            else _blocked(str(error), error.cleanup)
        )
        sys.stdout.buffer.write(canonical_json_bytes(blocked) + b"\n")
        return 2
    sys.stdout.buffer.write(canonical_json_bytes(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
