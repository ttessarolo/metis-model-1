"""Fail-closed bridge to the pinned, read-only Metis compiler.

The bridge deliberately keeps the compiler process outside this Python
package.  It sends one canonical JSON request to the TypeScript runner and
stores one canonical evidence envelope in a caller-supplied path outside the
Metis checkout.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

PINNED_METIS_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
PINNED_METIS_TREE = "75473e26deff4084a0eb077a4c3e27d52dc07998"
PINNED_NODE_VERSION = "v22.22.3"
PINNED_TOOLING_PACKAGE_SHA256 = "f8130a67f948720b339695fae614f32185610f762d69b85ff600f08971f2fb80"
PINNED_TOOLING_LOCK_SHA256 = "fed109b62f300ed824201f4b167d700072008b0b4a817cbb512a2eee32edc9fb"
PINNED_NODE_MODULES_SHA256 = "1cea5f2f0371d3c57b9ef9787707bc1079f88dc697c7be2c6c247e4018f6e463"
PINNED_RUNNER_SHA256 = "772baa27e981f611681330bc463aef2ebe06b5f4a83ef2a0313ccf66b6dfef5d"
PINNED_LOADER_SHA256 = "45e3557ce7ee345e2bca7de603c2ef8bc21aa2adb3f305d3f1cf6ee445273fee"
PINNED_NODE_BINARY_SHA256 = "5d9d3872911e2340a43b707962e68143de8a4e8d54628845c0c4f2de1fb7cd5c"
PINNED_NODE_BYTES = 112_915_776
LOADER_FLAGS = ("--disable-warning=ExperimentalWarning", "--experimental-loader")
NODE_RUNTIME_IDENTITY = "node://v22.22.3"
NODE_RUNTIME_ENV = "METIS_MODEL1_NODE"
NATIVE_TRACE_FD_ENV = "METIS_MODEL1_NATIVE_TRACE_FD"
SANDBOX_EXEC_PATH = Path("/usr/bin/sandbox-exec")
SANDBOX_EXEC_IDENTITY = "sandbox-exec:///usr/bin/sandbox-exec"
SANDBOX_POLICY = "(version 1) (allow default) (deny file-write*) (deny network*)"
SANDBOX_POLICY_SHA256 = "deb8f45c9dfc2f336dbfb6f69a13e599a51929864ede8229969fa7f6e03f40aa"
SANDBOX_POLICY_VERSION = "2"
STERILE_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
EXECUTION_MODES = frozenset({"endpoint", "source"})
NETWORK_CANARY_PROGRAM = """\
import errno
import socket
import sys

operation = sys.argv[1]
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    if operation == "connect":
        sock.connect(("127.0.0.1", 0))
    elif operation == "bind":
        sock.bind(("127.0.0.1", 0))
    else:
        sys.exit(5)
except OSError as error:
    sys.exit(0 if error.errno in {errno.EPERM, errno.EACCES} else 3)
sys.exit(4)
"""
LANGUAGE_VERSION = "0.43"
SCHEMA_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = (PROJECT_ROOT / "artifacts").resolve()
RUNNER_PATH = (PROJECT_ROOT / "runtime/metis_oracle/runner.ts").resolve()
LOADER_PATH = (PROJECT_ROOT / "runtime/metis_oracle/native_ts_loader.mjs").resolve()
SCHEMA_PATH = PROJECT_ROOT / "schemas/oracle-result.schema.json"
CAPSULE_PROTOCOL = "metis-runtime-capsule-v3"
CAPSULE_SCHEMA_VERSION = 3
CAPSULE_MANIFEST_NAME = "capsule.json"
MAX_CAPSULE_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_CAPSULE_FILE_BYTES = 256 * 1024 * 1024
MAX_CAPSULE_STDOUT_BYTES = 8 * 1024 * 1024
MAX_CAPSULE_STDERR_BYTES = 64 * 1024
CAPSULE_ANCESTOR_SLOTS = 32
RUNTIME_ANCESTOR_SLOTS = 32
EXECUTED_PREIMAGE_AUTHORITY = False
REGISTERED_PROTECTED_EXECUTION_BROKER_SHA256: str | None = None
_CAPSULE_ANCESTOR_POLICY = "\n".join(
    f'  (literal (param "CAPSULE_ANCESTOR_{index:02d}"))' for index in range(CAPSULE_ANCESTOR_SLOTS)
)
_RUNTIME_ANCESTOR_POLICY = "\n".join(
    f'  (literal (param "RUNTIME_ANCESTOR_{index:02d}"))' for index in range(RUNTIME_ANCESTOR_SLOTS)
)
CAPSULE_EXECUTION_POLICY_TEMPLATE = (
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
    + _CAPSULE_ANCESTOR_POLICY
    + "\n"
    + _RUNTIME_ANCESTOR_POLICY
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
CAPSULE_EXECUTION_POLICY = {
    "sandbox_policy_sha256": (
        "sha256:" + hashlib.sha256(CAPSULE_EXECUTION_POLICY_TEMPLATE.encode("utf-8")).hexdigest()
    ),
    "capsule_ancestor_slots": CAPSULE_ANCESTOR_SLOTS,
    "runtime_ancestor_slots": RUNTIME_ANCESTOR_SLOTS,
    "process_fork": "denied",
    "supervision": "node-session-group-leader",
    "loader_flags": list(LOADER_FLAGS),
}
CAPSULE_REQUEST_KEYS = frozenset(
    {
        "schema_version",
        "protocol",
        "execution_id",
        "run_nonce",
        "capsule_manifest_sha256",
        "request",
    }
)
CAPSULE_MANIFEST_KEYS = frozenset(
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
    }
)


class OracleError(ValueError):
    """Raised when an oracle result cannot be trusted."""


def _capsule_production_environment() -> dict[str, str]:
    environment = {"PATH": "", "LANG": "C", "LC_ALL": "C"}
    if NATIVE_TRACE_FD_ENV in environment:
        raise OracleError("production capsule environment enables reference tracing")
    return environment


def _require_protected_execution_broker() -> None:
    if REGISTERED_PROTECTED_EXECUTION_BROKER_SHA256 is None:
        raise OracleError("capsule execution requires a protected execution broker authority")
    raise OracleError("protected execution broker transport is not implemented")


MetisOracleError = OracleError


def _canonical(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise OracleError(f"oracle evidence is not canonical JSON: {error}") from error
    return rendered.encode()


def _sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exact_object(value: Any, keys: set[str] | frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise OracleError(f"{label} does not have the exact registered fields")
    return value


def _safe_capsule_path(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise OracleError(f"{label} is not a safe relative POSIX path")
    path = PurePosixPath(value)
    lowered = {part.lower() for part in path.parts}
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
        or ".git" in lowered
        or any(part == ".env" or part.startswith(".env.") for part in lowered)
    ):
        raise OracleError(f"{label} is forbidden")
    return path


def _read_exact_regular(path: Path, limit: int, label: str) -> bytes:
    try:
        before = path.lstat()
    except OSError as error:
        raise OracleError(f"{label} is unavailable") from error
    if path.is_symlink() or not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise OracleError(f"{label} must be a bounded regular non-symlink file")
    try:
        raw = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise OracleError(f"{label} cannot be read") from error
    identity = lambda item: (  # noqa: E731 - compact immutable stat identity
        item.st_dev,
        item.st_ino,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
        item.st_mode,
    )
    if identity(before) != identity(after) or len(raw) != before.st_size:
        raise OracleError(f"{label} changed while it was read")
    return raw


def _capsule_file(root: Path, relative: PurePosixPath, label: str) -> Path:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise OracleError(f"{label} crosses a symlink")
    try:
        resolved = current.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise OracleError(f"{label} is unavailable") from error
    if not _contains(root, resolved):
        raise OracleError(f"{label} escapes the capsule root")
    return resolved


def validate_runtime_capsule_descriptor(value: Any) -> dict[str, Any]:
    """Validate the exact v3 capsule descriptor without touching its filesystem root."""

    manifest = _exact_object(value, CAPSULE_MANIFEST_KEYS, "runtime capsule manifest")
    if (
        type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != CAPSULE_SCHEMA_VERSION
        or not isinstance(manifest["capsule_id"], str)
        or not manifest["capsule_id"]
        or manifest["revision"] != PINNED_METIS_REVISION
        or manifest["tree"] != PINNED_METIS_TREE
        or manifest["language_version"] != LANGUAGE_VERSION
    ):
        raise OracleError("runtime capsule identity drifted")
    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise OracleError("runtime capsule file roster is empty")
    registered: dict[str, dict[str, Any]] = {}
    byte_total = 0
    for index, record_value in enumerate(files):
        record = _exact_object(
            record_value,
            {"path", "size", "mode", "sha256", "role"},
            f"runtime capsule file {index}",
        )
        relative = _safe_capsule_path(record["path"], f"runtime capsule file {index} path")
        name = relative.as_posix()
        if (
            name == CAPSULE_MANIFEST_NAME
            or name in registered
            or type(record["size"]) is not int
            or record["size"] < 0
            or type(record["mode"]) is not int
            or record["mode"] not in {0o444, 0o555}
            or not isinstance(record["sha256"], str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", record["sha256"])
            or record["role"] not in {"git-archive", "tooling", "loader", "runner"}
        ):
            raise OracleError("runtime capsule file record is invalid")
        registered[name] = record
        byte_total += record["size"]
    counts = _exact_object(manifest["counts"], {"files", "bytes"}, "capsule counts")
    if counts != {"files": len(files), "bytes": byte_total}:
        raise OracleError("runtime capsule counts differ from its roster")
    if manifest["roster_sha256"] != _sha(files):
        raise OracleError("runtime capsule roster digest is invalid")
    expected_identities = {
        "loader": {
            "path": ".metis-oracle/native_ts_loader.mjs",
            "sha256": "sha256:" + PINNED_LOADER_SHA256,
            "mode": 0o444,
        },
        "runner": {
            "path": ".metis-oracle/runner.ts",
            "sha256": "sha256:" + PINNED_RUNNER_SHA256,
            "mode": 0o444,
        },
    }
    for role, expected in expected_identities.items():
        identity = _exact_object(manifest[role], {"path", "sha256", "mode"}, f"capsule {role}")
        row = registered.get(expected["path"])
        if (
            identity != expected
            or row is None
            or any(row[field] != expected[field] for field in ("path", "sha256", "mode"))
            or row["role"] != role
        ):
            raise OracleError(f"capsule {role} identity differs from its exact pin")
    tooling = _exact_object(
        manifest["tooling"],
        {"package_sha256", "lock_sha256", "node_modules_sha256"},
        "capsule tooling",
    )
    if tooling != {
        "package_sha256": "sha256:" + PINNED_TOOLING_PACKAGE_SHA256,
        "lock_sha256": "sha256:" + PINNED_TOOLING_LOCK_SHA256,
        "node_modules_sha256": "sha256:" + PINNED_NODE_MODULES_SHA256,
    }:
        raise OracleError("capsule tooling identity differs from its pins")
    body = {key: item for key, item in manifest.items() if key != "manifest_sha256"}
    if manifest["manifest_sha256"] != _sha(body):
        raise OracleError("runtime capsule manifest digest is invalid")
    return manifest


def verify_runtime_capsule(
    capsule_root: str | os.PathLike[str],
    *,
    expected_manifest_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    """Verify an immutable, exact-roster runtime capsule without consulting Git."""

    root = _strict_canonical_path(
        capsule_root,
        "runtime capsule root",
        must_exist=True,
        directory=True,
    )
    if stat.S_IMODE(root.lstat().st_mode) != 0o555:
        raise OracleError("runtime capsule root mode differs from its immutable contract")
    raw = _read_exact_regular(
        root / CAPSULE_MANIFEST_NAME,
        MAX_CAPSULE_MANIFEST_BYTES,
        "runtime capsule manifest",
    )
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OracleError("runtime capsule manifest is not valid JSON") from error
    if raw != _canonical(manifest):
        raise OracleError("runtime capsule manifest is not canonical JSON")
    manifest = _exact_object(manifest, CAPSULE_MANIFEST_KEYS, "runtime capsule manifest")
    if (
        type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != CAPSULE_SCHEMA_VERSION
    ):
        raise OracleError("runtime capsule schema version is invalid")
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    measured_manifest = _sha(body)
    if (
        manifest["manifest_sha256"] != measured_manifest
        or measured_manifest != expected_manifest_sha256
    ):
        raise OracleError("runtime capsule manifest differs from its independent digest")
    validate_runtime_capsule_descriptor(manifest)
    if (
        manifest["revision"] != PINNED_METIS_REVISION
        or manifest["tree"] != PINNED_METIS_TREE
        or manifest["language_version"] != LANGUAGE_VERSION
    ):
        raise OracleError("runtime capsule revision, tree or language version drifted")

    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise OracleError("runtime capsule file roster is empty")
    registered: dict[str, dict[str, Any]] = {}
    byte_total = 0
    for index, record in enumerate(files):
        record = _exact_object(
            record,
            {"path", "size", "mode", "sha256", "role"},
            f"runtime capsule file {index}",
        )
        relative = _safe_capsule_path(record["path"], f"runtime capsule file {index} path")
        name = relative.as_posix()
        if name == CAPSULE_MANIFEST_NAME or name in registered:
            raise OracleError("runtime capsule file paths are not unique")
        if (
            type(record["size"]) is not int
            or record["size"] < 0
            or type(record["mode"]) is not int
            or record["mode"] not in {0o444, 0o555}
            or not isinstance(record["sha256"], str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", record["sha256"])
            or record["role"] not in {"git-archive", "tooling", "loader", "runner"}
        ):
            raise OracleError("runtime capsule file record is invalid")
        path = _capsule_file(root, relative, f"runtime capsule file {name}")
        content = _read_exact_regular(path, MAX_CAPSULE_FILE_BYTES, f"runtime capsule file {name}")
        if (
            len(content) != record["size"]
            or stat.S_IMODE(path.lstat().st_mode) != record["mode"]
            or "sha256:" + hashlib.sha256(content).hexdigest() != record["sha256"]
        ):
            raise OracleError(f"runtime capsule file {name} differs from its exact record")
        byte_total += len(content)
        registered[name] = record

    items = list(root.rglob("*"))
    if any(item.is_symlink() for item in items):
        raise OracleError("runtime capsule contains a symlink")
    actual_files = {
        item.relative_to(root).as_posix() for item in items if stat.S_ISREG(item.lstat().st_mode)
    }
    if actual_files != set(registered) | {CAPSULE_MANIFEST_NAME}:
        raise OracleError("runtime capsule contains missing, extra or untracked content")
    if any(stat.S_IMODE(item.lstat().st_mode) != 0o555 for item in items if item.is_dir()):
        raise OracleError("runtime capsule directory mode drifted")
    counts = _exact_object(manifest["counts"], {"files", "bytes"}, "capsule counts")
    if counts != {"files": len(registered), "bytes": byte_total}:
        raise OracleError("runtime capsule counts differ from the verified roster")
    if manifest["roster_sha256"] != _sha(files):
        raise OracleError("runtime capsule roster digest is invalid")

    identities = {
        "loader": (manifest["loader"], "loader"),
        "runner": (manifest["runner"], "runner"),
    }
    for label, (identity, role) in identities.items():
        identity = _exact_object(identity, {"path", "sha256", "mode"}, f"capsule {label}")
        record = registered.get(identity["path"])
        if (
            record is None
            or record["role"] != role
            or record["sha256"] != identity["sha256"]
            or record["mode"] != identity["mode"]
        ):
            raise OracleError(f"capsule {label} identity is not in the verified roster")
    if manifest["loader"] != {
        "path": ".metis-oracle/native_ts_loader.mjs",
        "sha256": "sha256:" + PINNED_LOADER_SHA256,
        "mode": 0o444,
    }:
        raise OracleError("capsule native loader identity differs from its pin")
    if manifest["runner"].get("sha256") != "sha256:" + PINNED_RUNNER_SHA256:
        raise OracleError("capsule runner identity differs from its pin")
    tooling = _exact_object(
        manifest["tooling"],
        {"package_sha256", "lock_sha256", "node_modules_sha256"},
        "capsule tooling",
    )
    if tooling != {
        "package_sha256": "sha256:" + PINNED_TOOLING_PACKAGE_SHA256,
        "lock_sha256": "sha256:" + PINNED_TOOLING_LOCK_SHA256,
        "node_modules_sha256": "sha256:" + PINNED_NODE_MODULES_SHA256,
    }:
        raise OracleError("capsule tooling identity differs from its pins")
    return root, manifest


def _capture_runtime_capsule_contents(root: Path, manifest: dict[str, Any]) -> dict[str, bytes]:
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise OracleError("runtime capsule preimage roster is unavailable")
    contents: dict[str, bytes] = {}
    for index, record in enumerate(records):
        record = _exact_object(
            record,
            {"path", "size", "mode", "sha256", "role"},
            f"runtime capsule preimage file {index}",
        )
        relative = _safe_capsule_path(record["path"], "runtime capsule preimage path")
        name = relative.as_posix()
        if name in contents or name == CAPSULE_MANIFEST_NAME:
            raise OracleError("runtime capsule preimage paths are not unique")
        path = _capsule_file(root, relative, f"runtime capsule preimage file {name}")
        raw = _read_exact_regular(path, MAX_CAPSULE_FILE_BYTES, f"runtime capsule file {name}")
        if (
            type(record["size"]) is not int
            or record["size"] != len(raw)
            or type(record["mode"]) is not int
            or record["mode"] not in {0o444, 0o555}
            or stat.S_IMODE(path.lstat().st_mode) != record["mode"]
            or record["sha256"] != "sha256:" + hashlib.sha256(raw).hexdigest()
        ):
            raise OracleError(f"runtime capsule preimage file {name} differs from its record")
        contents[name] = raw
    return contents


def _write_capsule_preimage_file_at(
    directory_fd: int,
    name: str,
    raw: bytes,
    mode: int,
) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            mode,
            dir_fd=directory_fd,
        )
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OracleError("runtime capsule preimage write was incomplete")
            view = view[written:]
        os.fchmod(descriptor, mode)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != mode
            or metadata.st_size != len(raw)
        ):
            raise OracleError("runtime capsule preimage file identity is invalid")
    except OracleError:
        raise
    except OSError as error:
        raise OracleError("runtime capsule preimage file could not be created securely") from error
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _open_capsule_preimage_directory_at(
    root_fd: int,
    parts: tuple[str, ...],
    *,
    create: bool,
) -> int:
    current_fd = -1
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        current_fd = os.dup(root_fd)
        for component in parts:
            if create:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(component, 0o700, dir_fd=current_fd)
            child_fd = -1
            try:
                child_fd = os.open(component, flags, dir_fd=current_fd)
                metadata = os.fstat(child_fd)
                if not stat.S_ISDIR(metadata.st_mode):
                    raise OracleError("runtime capsule preimage ancestry is invalid")
                os.close(current_fd)
                current_fd = child_fd
                child_fd = -1
            finally:
                if child_fd >= 0:
                    with contextlib.suppress(OSError):
                        os.close(child_fd)
        return current_fd
    except BaseException:
        with contextlib.suppress(OSError):
            if current_fd >= 0:
                os.close(current_fd)
        raise


def _read_capsule_preimage_file_at(
    root_fd: int,
    relative: PurePosixPath,
    limit: int,
    label: str,
) -> tuple[bytes, os.stat_result]:
    parent_fd = -1
    descriptor = -1
    try:
        parent_fd = _open_capsule_preimage_directory_at(
            root_fd,
            tuple(relative.parts[:-1]),
            create=False,
        )
        descriptor = os.open(
            relative.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise OracleError(f"{label} must be a bounded regular file")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise OracleError(f"{label} exceeds its cap")
        after = os.fstat(descriptor)
        identity = lambda item: (  # noqa: E731
            item.st_dev,
            item.st_ino,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
            item.st_mode,
        )
        if identity(before) != identity(after) or total != before.st_size:
            raise OracleError(f"{label} changed while it was read")
        return b"".join(chunks), after
    except OracleError:
        raise
    except OSError as error:
        raise OracleError(f"{label} cannot be read securely") from error
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if parent_fd >= 0:
            with contextlib.suppress(OSError):
                os.close(parent_fd)


def _capsule_preimage_roster_at(
    root_fd: int,
    prefix: PurePosixPath | None = None,
) -> tuple[set[str], dict[str, int]]:
    if prefix is None:
        prefix = PurePosixPath()
    files: set[str] = set()
    directories: dict[str, int] = {}
    try:
        names = os.listdir(root_fd)
    except OSError as error:
        raise OracleError("runtime capsule preimage roster cannot be listed securely") from error
    for name in names:
        if name in {"", ".", ".."} or "/" in name:
            raise OracleError("runtime capsule preimage roster contains an invalid name")
        metadata = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        relative = prefix / name
        rendered = relative.as_posix()
        if stat.S_ISREG(metadata.st_mode):
            files.add(rendered)
        elif stat.S_ISDIR(metadata.st_mode):
            directories[rendered] = stat.S_IMODE(metadata.st_mode)
            child_fd = -1
            try:
                child_fd = _open_capsule_preimage_directory_at(
                    root_fd,
                    (name,),
                    create=False,
                )
                child_files, child_directories = _capsule_preimage_roster_at(child_fd, relative)
            finally:
                if child_fd >= 0:
                    with contextlib.suppress(OSError):
                        os.close(child_fd)
            files |= child_files
            directories.update(child_directories)
        else:
            raise OracleError("runtime capsule preimage contains a non-regular entry")
    return files, directories


def _directory_fd_matches_path(directory_fd: int, path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    opened = os.fstat(directory_fd)
    return (
        not stat.S_ISLNK(metadata.st_mode)
        and stat.S_ISDIR(metadata.st_mode)
        and (opened.st_dev, opened.st_ino) == (metadata.st_dev, metadata.st_ino)
    )


def _file_fd_matches_path(file_fd: int, path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    opened = os.fstat(file_fd)
    return (
        not stat.S_ISLNK(metadata.st_mode)
        and stat.S_ISREG(metadata.st_mode)
        and (opened.st_dev, opened.st_ino) == (metadata.st_dev, metadata.st_ino)
    )


def _verify_runtime_capsule_preimage(
    root: Path,
    manifest: dict[str, Any],
    contents: dict[str, bytes],
) -> None:
    if root.is_symlink() or not root.is_dir() or stat.S_IMODE(root.lstat().st_mode) != 0o555:
        raise OracleError("runtime capsule preimage root is not immutable")
    items = list(root.rglob("*"))
    if any(item.is_symlink() or not (item.is_file() or item.is_dir()) for item in items):
        raise OracleError("runtime capsule preimage contains a non-regular entry")
    actual_files = {item.relative_to(root).as_posix() for item in items if item.is_file()}
    if actual_files != set(contents) | {CAPSULE_MANIFEST_NAME}:
        raise OracleError("runtime capsule preimage roster changed")
    if any(stat.S_IMODE(item.lstat().st_mode) != 0o555 for item in items if item.is_dir()):
        raise OracleError("runtime capsule preimage directory mode changed")
    manifest_raw = _read_exact_regular(
        root / CAPSULE_MANIFEST_NAME,
        MAX_CAPSULE_MANIFEST_BYTES,
        "runtime capsule preimage manifest",
    )
    if (
        manifest_raw != _canonical(manifest)
        or stat.S_IMODE((root / CAPSULE_MANIFEST_NAME).lstat().st_mode) != 0o444
    ):
        raise OracleError("runtime capsule preimage manifest changed")
    records = {record["path"]: record for record in manifest["files"]}
    for name, expected in contents.items():
        path = _capsule_file(root, _safe_capsule_path(name, "capsule preimage path"), name)
        raw = _read_exact_regular(path, MAX_CAPSULE_FILE_BYTES, f"capsule preimage file {name}")
        if raw != expected or stat.S_IMODE(path.lstat().st_mode) != records[name]["mode"]:
            raise OracleError(f"runtime capsule preimage file {name} changed")


def _verify_runtime_capsule_preimage_at(
    root_fd: int,
    manifest: dict[str, Any],
    contents: dict[str, bytes],
) -> None:
    root_metadata = os.fstat(root_fd)
    if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_IMODE(root_metadata.st_mode) != 0o555:
        raise OracleError("runtime capsule preimage opened root is not immutable")
    actual_files, directories = _capsule_preimage_roster_at(root_fd)
    if actual_files != set(contents) | {CAPSULE_MANIFEST_NAME}:
        raise OracleError("runtime capsule opened preimage roster changed")
    if any(mode != 0o555 for mode in directories.values()):
        raise OracleError("runtime capsule opened preimage directory mode changed")
    manifest_raw, manifest_metadata = _read_capsule_preimage_file_at(
        root_fd,
        PurePosixPath(CAPSULE_MANIFEST_NAME),
        MAX_CAPSULE_MANIFEST_BYTES,
        "runtime capsule opened preimage manifest",
    )
    if manifest_raw != _canonical(manifest) or stat.S_IMODE(manifest_metadata.st_mode) != 0o444:
        raise OracleError("runtime capsule opened preimage manifest changed")
    records = {record["path"]: record for record in manifest["files"]}
    for name, expected in contents.items():
        relative = _safe_capsule_path(name, "runtime capsule opened preimage path")
        raw, metadata = _read_capsule_preimage_file_at(
            root_fd,
            relative,
            MAX_CAPSULE_FILE_BYTES,
            f"runtime capsule opened preimage file {name}",
        )
        if raw != expected or stat.S_IMODE(metadata.st_mode) != records[name]["mode"]:
            raise OracleError(f"runtime capsule opened preimage file {name} changed")


def _materialize_runtime_capsule_preimage(
    invocation: Path,
    invocation_fd: int,
    manifest: dict[str, Any],
    contents: dict[str, bytes],
) -> tuple[Path, int]:
    manifest_sha256 = manifest.get("manifest_sha256")
    if (
        not isinstance(manifest_sha256, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_sha256) is None
    ):
        raise OracleError("runtime capsule preimage content address is invalid")
    records = {record["path"]: record for record in manifest["files"]}
    if set(records) != set(contents):
        raise OracleError("runtime capsule preimage byte roster is incomplete")
    target_name = f"capsule-{manifest_sha256[7:]}"
    target = invocation / target_name
    target_fd = -1
    try:
        os.mkdir(target_name, 0o700, dir_fd=invocation_fd)
        target_fd = os.open(
            target_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=invocation_fd,
        )
        all_files = {CAPSULE_MANIFEST_NAME: _canonical(manifest), **contents}
        modes = {
            CAPSULE_MANIFEST_NAME: 0o444,
            **{name: record["mode"] for name, record in records.items()},
        }
        for name in sorted(all_files):
            relative = _safe_capsule_path(name, "runtime capsule preimage path")
            parent_fd = -1
            try:
                parent_fd = _open_capsule_preimage_directory_at(
                    target_fd,
                    tuple(relative.parts[:-1]),
                    create=True,
                )
                _write_capsule_preimage_file_at(
                    parent_fd,
                    relative.name,
                    all_files[name],
                    modes[name],
                )
            finally:
                if parent_fd >= 0:
                    with contextlib.suppress(OSError):
                        os.close(parent_fd)
        directory_paths = {
            parent
            for name in all_files
            for parent in PurePosixPath(name).parents
            if parent.as_posix() != "."
        }
        for relative in sorted(directory_paths, key=lambda value: len(value.parts), reverse=True):
            directory_fd = -1
            try:
                directory_fd = _open_capsule_preimage_directory_at(
                    target_fd,
                    tuple(relative.parts),
                    create=False,
                )
                os.fchmod(directory_fd, 0o555)
            finally:
                if directory_fd >= 0:
                    with contextlib.suppress(OSError):
                        os.close(directory_fd)
        os.fchmod(target_fd, 0o555)
        _verify_runtime_capsule_preimage_at(target_fd, manifest, contents)
        if not _directory_fd_matches_path(
            invocation_fd, invocation
        ) or not _directory_fd_matches_path(target_fd, target):
            raise OracleError("runtime capsule preimage namespace changed during materialization")
        return target, target_fd
    except BaseException:
        if target_fd >= 0:
            with contextlib.suppress(OSError):
                os.close(target_fd)
        raise


@contextlib.contextmanager
def _owned_materialized_runtime_capsule_preimage(
    invocation: Path,
    invocation_fd: int,
    manifest: dict[str, Any],
    contents: dict[str, bytes],
) -> Iterator[tuple[Path, int]]:
    """Keep the materializer descriptor owned until the caller has finished setup."""

    preimage_fd = -1
    try:
        preimage, preimage_fd = _materialize_runtime_capsule_preimage(
            invocation,
            invocation_fd,
            manifest,
            contents,
        )
        yield preimage, preimage_fd
    finally:
        if preimage_fd >= 0:
            with contextlib.suppress(OSError):
                os.close(preimage_fd)


def _assert_sandbox_policy() -> None:
    """Prove the registered sandbox denies writes and local network syscalls."""

    if (
        not SANDBOX_EXEC_PATH.is_file()
        or not os.access(SANDBOX_EXEC_PATH, os.X_OK)
        or hashlib.sha256(SANDBOX_POLICY.encode()).hexdigest() != SANDBOX_POLICY_SHA256
    ):
        raise OracleError("registered sandbox-exec policy is unavailable")
    try:
        probe = subprocess.run(
            [str(SANDBOX_EXEC_PATH), "-p", SANDBOX_POLICY, "/usr/bin/true"],
            env=STERILE_ENV,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OracleError(f"cannot start registered sandbox-exec policy: {error}") from error
    if probe.returncode != 0:
        raise OracleError("registered sandbox-exec policy failed its harmless probe")
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    canary_dir = Path(tempfile.mkdtemp(prefix="metis-oracle-sandbox-canary-", dir=ARTIFACT_ROOT))
    canary = canary_dir / "write-denied"
    try:
        command = f"printf x > {shlex.quote(str(canary))}"
        try:
            attempt = subprocess.run(
                [str(SANDBOX_EXEC_PATH), "-p", SANDBOX_POLICY, "/bin/sh", "-c", command],
                env=STERILE_ENV,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise OracleError(f"cannot execute sandbox write canary: {error}") from error
        if attempt.returncode == 0 or canary.exists():
            raise OracleError("registered sandbox-exec policy failed to deny file writes")
        for operation in ("connect", "bind"):
            try:
                network_attempt = subprocess.run(
                    [
                        str(SANDBOX_EXEC_PATH),
                        "-p",
                        SANDBOX_POLICY,
                        "/usr/bin/python3",
                        "-c",
                        NETWORK_CANARY_PROGRAM,
                        operation,
                    ],
                    env=STERILE_ENV,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise OracleError(f"cannot execute sandbox {operation} canary: {error}") from error
            if network_attempt.returncode != 0:
                raise OracleError(
                    f"registered sandbox-exec policy failed to deny network {operation}"
                )
    finally:
        shutil.rmtree(canary_dir, ignore_errors=True)


def _validate_node_binary(node: str | os.PathLike[str] | None) -> tuple[Path, str]:
    if node is None:
        raise OracleError(
            f"node runtime mismatch: expected {PINNED_NODE_VERSION}, node was not found on PATH"
        )
    try:
        resolved = Path(node).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise OracleError("pinned Node binary path is invalid") from error
    metadata = resolved.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o755
        or metadata.st_nlink != 1
        or metadata.st_size != PINNED_NODE_BYTES
        or not os.access(resolved, os.X_OK)
    ):
        raise OracleError("pinned Node binary must be an executable file")
    digest = _file_sha256(resolved)
    if digest != PINNED_NODE_BINARY_SHA256:
        raise OracleError("node runtime mismatch: Node binary hash differs from its pin")
    # Never execute this mutable source path. It is copied into the isolated
    # snapshot and re-hashed before sandboxed execution; the runner then reports
    # ``process.version``, which the response validator binds to the version pin.
    return resolved, digest


def _resolve_pinned_node() -> tuple[Path, str]:
    """Resolve only the registered Node binary, independent of PATH order."""

    configured = os.environ.get(NODE_RUNTIME_ENV)
    if configured is not None:
        if not configured or not Path(configured).is_absolute():
            raise OracleError(f"{NODE_RUNTIME_ENV} must be an absolute executable path")
        try:
            return _validate_node_binary(configured)
        except OSError as error:
            raise OracleError(f"cannot read {NODE_RUNTIME_ENV} binary") from error

    seen: set[Path] = set()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / "node"
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved in seen or not resolved.is_file() or not os.access(resolved, os.X_OK):
            continue
        seen.add(resolved)
        try:
            return _validate_node_binary(resolved)
        except (OSError, OracleError):
            continue
    raise OracleError(
        f"node runtime mismatch: no {PINNED_NODE_VERSION} binary matching the registered hash"
    )


def _node_modules_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        if path.is_symlink():
            digest.update(b"L\0" + relative + b"\0" + os.readlink(path).encode() + b"\0")
        elif path.is_file():
            digest.update(b"F\0" + relative + b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
    value = digest.hexdigest()
    return value


def _validate_tree_symlinks(root: Path, label: str) -> None:
    """Reject links which could make the isolated runner reach outside root."""

    root = root.resolve()
    for path in root.rglob("*"):
        if path.is_symlink() and not _contains(root, path.resolve(strict=False)):
            raise OracleError(f"{label} contains a symlink escaping its root: {path}")


def _build_isolated_snapshot(
    root: Path,
    revision: str,
    tree: str,
    tooling_runtime: dict[str, str],
    runner: Path,
    node_binary: Path,
) -> tuple[tempfile.TemporaryDirectory[str], Path, Path, Path, Path, Path]:
    """Materialize only pinned Git objects plus a checked tooling dependency copy."""

    holder: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory(
        prefix="metis-oracle-snapshot-"
    )
    snapshot = Path(holder.name)
    archive = snapshot.with_name(f"{snapshot.name}.tar")
    try:
        with archive.open("wb") as stream:
            completed = subprocess.run(
                ["git", "-C", str(root), "archive", "--format=tar", revision],
                check=True,
                stdout=stream,
                stderr=subprocess.PIPE,
                timeout=30,
                text=False,
            )
        del completed
        with archive.open("rb") as stream, tarfile.open(fileobj=stream, mode="r:") as bundle:
            # ``data`` prevents absolute and traversal members on supported Python versions.
            bundle.extractall(snapshot, filter="data")
    except (OSError, subprocess.SubprocessError, tarfile.TarError, ValueError) as error:
        holder.cleanup()
        raise OracleError(f"cannot materialize the pinned Metis snapshot: {error}") from error
    finally:
        archive.unlink(missing_ok=True)

    tooling = snapshot / "tooling"
    source_modules = root / "tooling" / "node_modules"
    snapshot_modules = tooling / "node_modules"
    snapshot_runner = snapshot / ".metis-oracle" / "runner.ts"
    snapshot_loader = snapshot / ".metis-oracle" / "native_ts_loader.mjs"
    snapshot_node = snapshot / ".metis-oracle" / "node"
    try:
        if not tooling.is_dir():
            raise OracleError("pinned snapshot is missing tooling")
        shutil.copytree(source_modules, snapshot_modules, symlinks=True)
        snapshot_runner.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(runner, snapshot_runner)
        shutil.copyfile(LOADER_PATH, snapshot_loader)
        shutil.copyfile(node_binary, snapshot_node)
        shutil.copymode(node_binary, snapshot_node)
        if _file_sha256(snapshot_runner) != PINNED_RUNNER_SHA256:
            raise OracleError("isolated runner differs from its pin")
        if _file_sha256(snapshot_loader) != PINNED_LOADER_SHA256:
            raise OracleError("isolated native loader differs from its pin")
        if _file_sha256(snapshot_node) != PINNED_NODE_BINARY_SHA256:
            raise OracleError("isolated Node binary differs from its pin")
        _validate_tree_symlinks(snapshot, "Metis snapshot")
        if _file_sha256(tooling / "package.json") != tooling_runtime["package_sha256"]:
            raise OracleError("snapshot tooling package.json differs from its pin")
        if _file_sha256(tooling / "package-lock.json") != tooling_runtime["lock_sha256"]:
            raise OracleError("snapshot tooling package-lock.json differs from its pin")
        if _node_modules_sha256(snapshot_modules) != tooling_runtime["node_modules_sha256"]:
            raise OracleError("snapshot node_modules differs from its pin")
        identity = {
            "revision": revision,
            "tree": tree,
            "package_sha256": tooling_runtime["package_sha256"],
            "lock_sha256": tooling_runtime["lock_sha256"],
            "node_modules_sha256": tooling_runtime["node_modules_sha256"],
            "runner_sha256": PINNED_RUNNER_SHA256,
            "loader_sha256": PINNED_LOADER_SHA256,
            "loader_flags": list(LOADER_FLAGS),
            "node_binary_sha256": PINNED_NODE_BINARY_SHA256,
            "sandbox_exec_path": SANDBOX_EXEC_IDENTITY,
            "oracle_policy_version": SANDBOX_POLICY_VERSION,
            "oracle_policy_sha256": SANDBOX_POLICY_SHA256,
            "execution_policy_sha256": SANDBOX_POLICY_SHA256,
        }
        (snapshot / ".metis-oracle-identity.json").write_bytes(_canonical(identity))
    except (OSError, shutil.Error, OracleError) as error:
        holder.cleanup()
        raise OracleError(f"cannot prepare the isolated Metis tooling: {error}") from error
    return holder, snapshot, snapshot_modules, snapshot_runner, snapshot_loader, snapshot_node


_DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_MAX_ORACLE_SESSION_ROSTER_ENTRIES = 65_536


def _metadata_identity(metadata: os.stat_result) -> tuple[int, ...]:
    """Return every unprivileged mutation-sensitive field exposed by ``stat``."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        int(getattr(metadata, "st_flags", 0)),
        int(getattr(metadata, "st_gen", 0)),
    )


def _regular_file_metadata(path: Path, label: str) -> tuple[int, ...]:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise OracleError(f"{label} is unavailable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise OracleError(f"{label} must remain a regular non-symlink file")
    return _metadata_identity(metadata)


def _open_metadata_directory(path: Path, label: str) -> int:
    descriptor = -1
    try:
        descriptor = os.open(path, _DIRECTORY_OPEN_FLAGS)
        if not _directory_fd_matches_path(descriptor, path):
            raise OracleError(f"{label} identity changed while opening it")
        return descriptor
    except BaseException:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        raise


def _directory_metadata_roster(directory_fd: int) -> tuple[tuple[Any, ...], ...]:
    """Inventory a tree through directory descriptors without following links."""

    roster: list[tuple[Any, ...]] = []

    def append(entry: tuple[Any, ...]) -> None:
        if len(roster) >= _MAX_ORACLE_SESSION_ROSTER_ENTRIES:
            raise OracleError("oracle session authority roster exceeds its bound")
        roster.append(entry)

    def visit(
        parent_fd: int,
        prefix: str,
        expected_identity: tuple[int, ...] | None,
    ) -> None:
        try:
            before = os.fstat(parent_fd)
        except OSError as error:
            raise OracleError("oracle session authority roster is unavailable") from error
        if not stat.S_ISDIR(before.st_mode):
            raise OracleError("oracle session authority roster root is not a directory")
        before_identity = _metadata_identity(before)
        if expected_identity is not None and before_identity != expected_identity:
            raise OracleError("oracle session authority directory changed during traversal")
        if not prefix:
            append(("", "directory", *before_identity, None))
        try:
            names = sorted(os.listdir(parent_fd))
        except OSError as error:
            raise OracleError("oracle session authority roster is unavailable") from error
        for name in names:
            if not isinstance(name, str) or not name or "/" in name or name in {".", ".."}:
                raise OracleError("oracle session authority roster contains an invalid name")
            relative = name if not prefix else f"{prefix}/{name}"
            try:
                metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except OSError as error:
                raise OracleError(
                    "oracle session authority roster changed during traversal"
                ) from error
            identity = _metadata_identity(metadata)
            if stat.S_ISDIR(metadata.st_mode):
                kind = "directory"
                target: str | None = None
            elif stat.S_ISREG(metadata.st_mode):
                kind = "file"
                target = None
            elif stat.S_ISLNK(metadata.st_mode):
                kind = "symlink"
                try:
                    target = os.readlink(name, dir_fd=parent_fd)
                except OSError as error:
                    raise OracleError(
                        "oracle session authority symlink changed during traversal"
                    ) from error
            else:
                raise OracleError("oracle session authority contains a non-regular entry")
            append((relative, kind, *identity, target))
            if kind != "directory":
                continue
            child_fd = -1
            try:
                child_fd = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_fd)
                opened = os.fstat(child_fd)
                if _metadata_identity(opened) != identity:
                    raise OracleError("oracle session authority directory changed during traversal")
                visit(child_fd, relative, identity)
            finally:
                if child_fd >= 0:
                    with contextlib.suppress(OSError):
                        os.close(child_fd)
        try:
            after_identity = _metadata_identity(os.fstat(parent_fd))
        except OSError as error:
            raise OracleError("oracle session authority roster is unavailable") from error
        if after_identity != before_identity:
            raise OracleError("oracle session authority directory changed during traversal")

    visit(directory_fd, "", None)
    return tuple(roster)


def _oracle_session_global_identity() -> tuple[Any, ...]:
    """Bind process globals which influence an old-oracle execution."""

    return (
        PINNED_METIS_REVISION,
        PINNED_METIS_TREE,
        PINNED_NODE_VERSION,
        PINNED_TOOLING_PACKAGE_SHA256,
        PINNED_TOOLING_LOCK_SHA256,
        PINNED_NODE_MODULES_SHA256,
        PINNED_RUNNER_SHA256,
        PINNED_LOADER_SHA256,
        PINNED_NODE_BINARY_SHA256,
        PINNED_NODE_BYTES,
        tuple(LOADER_FLAGS),
        NODE_RUNTIME_IDENTITY,
        NODE_RUNTIME_ENV,
        str(SANDBOX_EXEC_PATH),
        SANDBOX_EXEC_IDENTITY,
        SANDBOX_POLICY,
        SANDBOX_POLICY_SHA256,
        SANDBOX_POLICY_VERSION,
        _MAX_ORACLE_SESSION_ROSTER_ENTRIES,
        tuple(sorted(STERILE_ENV.items())),
        tuple(sorted(EXECUTION_MODES)),
        LANGUAGE_VERSION,
        SCHEMA_VERSION,
        str(ARTIFACT_ROOT),
        str(RUNNER_PATH),
        str(LOADER_PATH),
        str(SCHEMA_PATH),
    )


def _resolve_absolute(path: str | os.PathLike[str], label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise OracleError(f"{label} must be absolute")
    return Path(os.path.abspath(candidate))


def _contains(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _strict_canonical_path(
    value: str | os.PathLike[str],
    label: str,
    *,
    must_exist: bool,
    directory: bool | None = None,
) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or raw != os.path.abspath(raw):
        raise OracleError(f"{label} must be a lexical-canonical absolute path")
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
            raise OracleError(f"{label} ancestry is unavailable") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise OracleError(f"{label} ancestry contains a symlink")
    if must_exist and missing:
        raise OracleError(f"{label} is unavailable")
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as error:
        raise OracleError(f"{label} is unavailable") from error
    if resolved != candidate:
        raise OracleError(f"{label} is not lexical-canonical")
    if not missing and directory is True and not candidate.is_dir():
        raise OracleError(f"{label} is not a directory")
    if not missing and directory is False and not candidate.is_file():
        raise OracleError(f"{label} is not a file")
    return candidate


def _reject_symlink_parents(path: Path, label: str) -> None:
    cursor = path.parent
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise OracleError(f"{label} parent contains a symlink")
        cursor = cursor.parent


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OracleError(f"cannot inspect Metis Git repository: {error}") from error
    return completed.stdout.strip()


def validate_pinned_metis(
    metis_root: str | os.PathLike[str],
    *,
    expected_revision: str = PINNED_METIS_REVISION,
) -> tuple[Path, str, str, dict[str, str]]:
    """Validate the repository identity and return root, revision and tree hash."""

    root = _resolve_absolute(metis_root, "metis_root").resolve(strict=True)
    if not root.is_dir():
        raise OracleError("metis_root must be an existing directory")
    if expected_revision != PINNED_METIS_REVISION:
        raise OracleError("overriding the pinned Metis revision is forbidden")
    revision = _git(root, "rev-parse", "HEAD")
    if revision != expected_revision:
        raise OracleError(f"Metis revision mismatch: expected {expected_revision}, got {revision}")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    if tree != PINNED_METIS_TREE:
        raise OracleError("Metis tree does not match the pinned toolchain tree")
    tracked = _git(root, "status", "--porcelain=v1", "--untracked-files=no")
    if tracked:
        raise OracleError("Metis tracked working tree must match the pinned revision")
    tooling = root / "tooling"
    node_modules = (tooling / "node_modules").resolve(strict=True)
    if not tooling.is_dir() or not node_modules.is_dir():
        raise OracleError("pinned tooling/node_modules is required")
    package_sha256 = _file_sha256(tooling / "package.json")
    lock_sha256 = _file_sha256(tooling / "package-lock.json")
    modules_sha256 = _node_modules_sha256(node_modules)
    if package_sha256 != PINNED_TOOLING_PACKAGE_SHA256:
        raise OracleError("Metis tooling package.json differs from its pin")
    if lock_sha256 != PINNED_TOOLING_LOCK_SHA256:
        raise OracleError("Metis tooling package-lock.json differs from its pin")
    if modules_sha256 != PINNED_NODE_MODULES_SHA256:
        raise OracleError("Metis tooling node_modules differs from its pin")
    return (
        root,
        revision,
        tree,
        {
            "package_sha256": package_sha256,
            "lock_sha256": lock_sha256,
            "node_modules_sha256": modules_sha256,
        },
    )


def _validate_output_path(path: str | os.PathLike[str], metis_root: Path) -> Path:
    output = _resolve_absolute(path, "output_path")
    if output.suffix != ".json":
        raise OracleError("output_path must end in .json")
    if _contains(metis_root, output):
        raise OracleError("output_path may not be inside the Metis checkout")
    if not _contains(ARTIFACT_ROOT, output):
        raise OracleError("output_path must stay under the Model1 artifacts directory")
    _reject_symlink_parents(output, "output_path")
    if output.exists() and output.is_symlink():
        raise OracleError("output_path may not be a symlink")
    return output


def _validate_runner_path(path: str | os.PathLike[str], metis_root: Path) -> Path:
    runner = _resolve_absolute(path, "runner_path")
    if runner.suffix != ".ts" or not runner.is_file():
        raise OracleError("runner_path must be an existing TypeScript file")
    if _contains(metis_root, runner):
        raise OracleError("runner_path may not be inside the Metis checkout")
    _reject_symlink_parents(runner, "runner_path")
    if runner.is_symlink():
        raise OracleError("runner_path may not be a symlink")
    if runner.resolve() != RUNNER_PATH:
        raise OracleError("runner_path must be the pinned Model1 oracle runner")
    if _file_sha256(runner) != PINNED_RUNNER_SHA256:
        raise OracleError("oracle runner hash differs from its pin")
    return runner


def _runtime_identity_policy(
    revision: str,
    tree: str,
    tooling_runtime: dict[str, str] | None = None,
    *,
    execution_policy_sha256: str | None = None,
) -> dict[str, Any]:
    package_sha = PINNED_TOOLING_PACKAGE_SHA256
    lock_sha = PINNED_TOOLING_LOCK_SHA256
    modules_sha = PINNED_NODE_MODULES_SHA256
    if tooling_runtime is not None:
        package_sha = tooling_runtime["package_sha256"]
        lock_sha = tooling_runtime["lock_sha256"]
        modules_sha = tooling_runtime["node_modules_sha256"]
    execution_sha = execution_policy_sha256 or ("sha256:" + SANDBOX_POLICY_SHA256)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", execution_sha):
        raise OracleError("runtime execution policy identity is invalid")
    return {
        "node": PINNED_NODE_VERSION,
        "node_path": NODE_RUNTIME_IDENTITY,
        "loader_path": f"snapshot://{revision}/{tree}/.metis-oracle/native_ts_loader.mjs",
        "loader_sha256": "sha256:" + PINNED_LOADER_SHA256,
        "loader_flags": list(LOADER_FLAGS),
        "runner_path": f"snapshot://{revision}/{tree}/.metis-oracle/runner.ts",
        "snapshot_revision": revision,
        "snapshot_tree": tree,
        "tooling_package_sha256": "sha256:" + package_sha,
        "tooling_lock_sha256": "sha256:" + lock_sha,
        "node_modules_sha256": "sha256:" + modules_sha,
        "node_binary_sha256": "sha256:" + PINNED_NODE_BINARY_SHA256,
        "sandbox_exec_path": SANDBOX_EXEC_IDENTITY,
        "oracle_policy_version": SANDBOX_POLICY_VERSION,
        "oracle_policy_sha256": "sha256:" + SANDBOX_POLICY_SHA256,
        "execution_policy_sha256": execution_sha,
    }


def _runtime_identity(
    node_version: str,
    node_binary_sha256: str,
    revision: str,
    tree: str,
    tooling_runtime: dict[str, str],
) -> dict[str, Any]:
    if node_version != PINNED_NODE_VERSION:
        raise OracleError(
            f"node runtime mismatch: expected {PINNED_NODE_VERSION}, got {node_version}"
        )
    if node_binary_sha256 != PINNED_NODE_BINARY_SHA256:
        raise OracleError("Node binary hash differs from its pin")
    identity = _runtime_identity_policy(revision, tree, tooling_runtime)
    identity["node"] = node_version
    return identity


def _check_response(
    result: Any,
    revision: str,
    tree: str,
    *,
    expected_runtime: dict[str, Any] | None = None,
    expected_mode: str = "endpoint",
) -> dict[str, Any]:
    if expected_mode not in EXECUTION_MODES:
        raise OracleError("oracle execution mode is invalid")
    if not isinstance(result, dict) or result.get("schema_version") != SCHEMA_VERSION:
        raise OracleError("runner returned an invalid schema version")
    if result.get("status") not in {"ok", "invalid"}:
        raise OracleError("runner returned an invalid status")
    if result.get("toolchain", {}).get("revision") != revision:
        raise OracleError("runner toolchain revision does not match pinned HEAD")
    if result.get("toolchain", {}).get("tree") != tree:
        raise OracleError("runner toolchain tree does not match pinned HEAD")
    if result.get("toolchain", {}).get("language_version") != LANGUAGE_VERSION:
        raise OracleError("runner language version does not match the registered contract")
    diagnostics = result.get("diagnostics")
    ast = result.get("ast")
    ir = result.get("ir")
    if not isinstance(diagnostics, dict) or not isinstance(ast, dict) or not isinstance(ir, dict):
        raise OracleError("runner omitted diagnostics, AST or IR evidence")
    if ast.get("signature") != _sha(ast.get("inventory")):
        raise OracleError("runner AST signature is not deterministic")
    ir_value = ir.get("value")
    expected_ir = None if ir_value is None else _sha(ir_value)
    if ir.get("signature") != expected_ir:
        raise OracleError("runner IR signature is not deterministic")
    endpoint = result.get("endpoint")
    failure = result.get("failure")
    result_runtime = result.get("runtime")
    if not isinstance(endpoint, dict):
        raise OracleError("runner omitted endpoint evidence")
    if not isinstance(result_runtime, dict) or result_runtime.get("node") != PINNED_NODE_VERSION:
        raise OracleError("runner runtime identity does not match the pin")
    if (
        result_runtime.get("snapshot_revision") != revision
        or result_runtime.get("snapshot_tree") != tree
        or result_runtime.get("tooling_package_sha256") != "sha256:" + PINNED_TOOLING_PACKAGE_SHA256
        or result_runtime.get("tooling_lock_sha256") != "sha256:" + PINNED_TOOLING_LOCK_SHA256
        or result_runtime.get("node_modules_sha256") != "sha256:" + PINNED_NODE_MODULES_SHA256
        or result_runtime.get("node_binary_sha256") != "sha256:" + PINNED_NODE_BINARY_SHA256
        or result_runtime.get("loader_sha256") != "sha256:" + PINNED_LOADER_SHA256
        or result_runtime.get("loader_flags") != list(LOADER_FLAGS)
        or result_runtime.get("sandbox_exec_path") != SANDBOX_EXEC_IDENTITY
        or result_runtime.get("oracle_policy_version") != SANDBOX_POLICY_VERSION
        or result_runtime.get("oracle_policy_sha256") != "sha256:" + SANDBOX_POLICY_SHA256
        or not isinstance(result_runtime.get("execution_policy_sha256"), str)
    ):
        raise OracleError("runner runtime identity does not match the tooling pins")
    if expected_runtime is not None and result_runtime != expected_runtime:
        raise OracleError("runner runtime identity does not match the validated runtime")
    if result["status"] == "ok":
        validation_errors = [
            item
            for item in diagnostics.get("validation", [])
            if isinstance(item, dict) and item.get("severity") == 1
        ]
        common_inconsistency = (
            failure is not None
            or diagnostics.get("parser")
            or diagnostics.get("link")
            or validation_errors
        )
        endpoint_inconsistency = expected_mode == "endpoint" and (
            ir_value is None or endpoint.get("count") != 1
        )
        source_inconsistency = expected_mode == "source" and (
            ir_value is not None or endpoint.get("name") is not None
        )
        if common_inconsistency or endpoint_inconsistency or source_inconsistency:
            raise OracleError("runner returned a logically inconsistent ok result")
    elif ir_value is not None or not isinstance(failure, dict):
        raise OracleError("runner returned a logically inconsistent invalid result")
    return result


def _workspace_payload(workspace_sources: Any, filename: str) -> list[dict[str, str]]:
    if workspace_sources is None:
        return []
    if not isinstance(workspace_sources, dict):
        raise OracleError("workspace_sources must be a filename-to-source object")
    payload: list[dict[str, str]] = []
    for name, source in sorted(workspace_sources.items()):
        candidate = Path(name) if isinstance(name, str) else Path("")
        if (
            not isinstance(name, str)
            or not name
            or candidate.is_absolute()
            or ".." in candidate.parts
            or not name.endswith(".metis")
            or name == filename
            or not isinstance(source, str)
            or not source
        ):
            raise OracleError("workspace source paths and contents must be safe and non-empty")
        payload.append({"filename": name, "source": source})
    if len(payload) > 512:
        raise OracleError("workspace_sources exceeds the 512-document cap")
    return payload


def build_oracle_request(
    source: str,
    *,
    filename: str = "oracle.metis",
    execution_mode: str = "endpoint",
    endpoint: str | None = None,
    workspace_sources: dict[str, str] | None = None,
    revision: str = PINNED_METIS_REVISION,
    tree: str = PINNED_METIS_TREE,
) -> dict[str, Any]:
    """Build the exact canonical request later bound into the evidence envelope."""

    if not isinstance(source, str) or not source:
        raise OracleError("source must be a non-empty string")
    if (
        not isinstance(filename, str)
        or Path(filename).is_absolute()
        or not filename.endswith(".metis")
        or ".." in Path(filename).parts
    ):
        raise OracleError("filename must be a relative .metis name")
    if execution_mode not in EXECUTION_MODES:
        raise OracleError("execution_mode must be endpoint or source")
    if endpoint is not None and (not isinstance(endpoint, str) or not endpoint):
        raise OracleError("endpoint must be null or a non-empty string")
    if execution_mode == "source" and endpoint is not None:
        raise OracleError("source execution_mode requires a null endpoint")
    if revision != PINNED_METIS_REVISION or tree != PINNED_METIS_TREE:
        raise OracleError("oracle request toolchain identity differs from its pin")
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "filename": filename,
        "execution_mode": execution_mode,
        "endpoint": endpoint,
        "metis_root": f"snapshot://{revision}/{tree}",
        "metis_revision": revision,
        "metis_tree": tree,
        "workspace_sources": _workspace_payload(workspace_sources, filename),
    }


def verify_oracle_envelope(
    envelope: Any,
    *,
    request: Any | None = None,
    expected_execution_policy_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify a materialized oracle envelope without executing the compiler."""

    if not isinstance(envelope, dict):
        raise OracleError("oracle envelope must be an object")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(envelope), key=lambda item: list(item.path)
    )
    if errors:
        raise OracleError(f"oracle envelope violates its schema: {errors[0].message}")
    evidence = envelope["evidence"]
    unsigned = json.loads(_canonical(envelope))
    stored_envelope_sha256 = unsigned["evidence"].pop("envelope_sha256")
    if stored_envelope_sha256 != _sha(unsigned):
        raise OracleError("oracle envelope hash does not match its contents")
    expected_runtime = _runtime_identity_policy(
        evidence["toolchain_revision"],
        evidence["toolchain_tree"],
        execution_policy_sha256=expected_execution_policy_sha256,
    )
    if evidence["runtime_identity"] != expected_runtime:
        raise OracleError("oracle runtime identity does not match the immutable runtime policy")
    expected_mode = "endpoint"
    if request is not None:
        if not isinstance(request, dict) or request.get("execution_mode") not in EXECUTION_MODES:
            raise OracleError("supplied oracle request has an invalid execution mode")
        expected_mode = request["execution_mode"]
    result = _check_response(
        envelope["result"],
        evidence["toolchain_revision"],
        evidence["toolchain_tree"],
        expected_runtime=expected_runtime,
        expected_mode=expected_mode,
    )
    if evidence["diagnostics_sha256"] != _sha(result["diagnostics"]):
        raise OracleError("oracle diagnostics hash does not match")
    if evidence["ast_sha256"] != _sha(result["ast"]["inventory"]):
        raise OracleError("oracle AST hash does not match")
    expected_ir = None if result["ir"]["value"] is None else _sha(result["ir"]["value"])
    if evidence["ir_sha256"] != expected_ir:
        raise OracleError("oracle IR hash does not match")
    if evidence["runtime_sha256"] != _sha(evidence["runtime_identity"]):
        raise OracleError("oracle runtime hash does not match")
    if result["runtime"] != evidence["runtime_identity"]:
        raise OracleError("oracle result runtime is not bound to runtime_identity")
    if evidence["metis_status_sha256"] != _sha(evidence["metis_status"]):
        raise OracleError("oracle Metis status hash does not match")
    expected_pins = {
        "runner_sha256": "sha256:" + PINNED_RUNNER_SHA256,
        "loader_sha256": "sha256:" + PINNED_LOADER_SHA256,
        "tooling_package_sha256": "sha256:" + PINNED_TOOLING_PACKAGE_SHA256,
        "tooling_lock_sha256": "sha256:" + PINNED_TOOLING_LOCK_SHA256,
        "node_modules_sha256": "sha256:" + PINNED_NODE_MODULES_SHA256,
        "node_binary_sha256": "sha256:" + PINNED_NODE_BINARY_SHA256,
        "oracle_policy_sha256": "sha256:" + SANDBOX_POLICY_SHA256,
        "execution_policy_sha256": expected_runtime["execution_policy_sha256"],
        "toolchain_revision": PINNED_METIS_REVISION,
        "toolchain_tree": PINNED_METIS_TREE,
    }
    if any(evidence.get(field) != value for field, value in expected_pins.items()):
        raise OracleError("oracle evidence does not match the registered toolchain pins")
    if request is not None and evidence["input_sha256"] != _sha(request):
        raise OracleError("oracle input hash does not match the supplied request")
    return envelope


def _validate_capsule_request(value: Any) -> dict[str, Any]:
    request = _exact_object(value, CAPSULE_REQUEST_KEYS, "capsule oracle request")
    if (
        type(request["schema_version"]) is not int
        or request["schema_version"] != CAPSULE_SCHEMA_VERSION
        or request["protocol"] != CAPSULE_PROTOCOL
        or not isinstance(request["execution_id"], str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", request["execution_id"]) is None
        or not isinstance(request["run_nonce"], str)
        or re.fullmatch(r"[0-9a-f]{64}", request["run_nonce"]) is None
        or not isinstance(request["capsule_manifest_sha256"], str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", request["capsule_manifest_sha256"]) is None
    ):
        raise OracleError("capsule oracle request identity is invalid")
    semantic = request["request"]
    if not isinstance(semantic, dict):
        raise OracleError("capsule oracle semantic request is missing")
    rebuilt = build_oracle_request(
        semantic.get("source"),
        filename=semantic.get("filename"),
        execution_mode=semantic.get("execution_mode"),
        endpoint=semantic.get("endpoint"),
        workspace_sources={
            row["filename"]: row["source"]
            for row in semantic.get("workspace_sources", [])
            if isinstance(row, dict) and set(row) == {"filename", "source"}
        }
        if isinstance(semantic.get("workspace_sources"), list)
        else None,
        revision=semantic.get("metis_revision"),
        tree=semantic.get("metis_tree"),
    )
    if semantic != rebuilt:
        raise OracleError("capsule oracle semantic request is not canonical")
    return request


def normalize_capsule_oracle_envelope(envelope: Any) -> dict[str, Any]:
    """Remove only the modeled execution nonce from a verified capsule envelope."""

    verified = verify_capsule_oracle_envelope(envelope)
    return {key: value for key, value in verified.items() if key != "run_nonce"}


def verify_capsule_oracle_envelope(
    envelope: Any,
    *,
    capsule_request: Any | None = None,
) -> dict[str, Any]:
    keys = {
        "schema_version",
        "protocol",
        "execution_id",
        "run_nonce",
        "request_sha256",
        "capsule_manifest_sha256",
        "execution_policy",
        "oracle_envelope",
        "manifest_sha256",
    }
    envelope = _exact_object(envelope, keys, "capsule oracle envelope")
    if (
        type(envelope["schema_version"]) is not int
        or envelope["schema_version"] != CAPSULE_SCHEMA_VERSION
        or envelope["protocol"] != CAPSULE_PROTOCOL
        or not isinstance(envelope["execution_id"], str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", envelope["execution_id"]) is None
        or not isinstance(envelope["run_nonce"], str)
        or re.fullmatch(r"[0-9a-f]{64}", envelope["run_nonce"]) is None
        or not isinstance(envelope["capsule_manifest_sha256"], str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", envelope["capsule_manifest_sha256"]) is None
        or envelope["execution_policy"] != CAPSULE_EXECUTION_POLICY
    ):
        raise OracleError("capsule oracle envelope identity is invalid")
    if capsule_request is not None:
        request = _validate_capsule_request(capsule_request)
        if (
            envelope["execution_id"] != request["execution_id"]
            or envelope["run_nonce"] != request["run_nonce"]
            or envelope["capsule_manifest_sha256"] != request["capsule_manifest_sha256"]
            or envelope["request_sha256"] != _sha(request["request"])
        ):
            raise OracleError("capsule oracle envelope differs from its request")
        verify_oracle_envelope(
            envelope["oracle_envelope"],
            request=request["request"],
            expected_execution_policy_sha256=CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"],
        )
    else:
        verify_oracle_envelope(
            envelope["oracle_envelope"],
            expected_execution_policy_sha256=CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"],
        )
    body = {
        key: value for key, value in envelope.items() if key not in {"run_nonce", "manifest_sha256"}
    }
    if envelope["manifest_sha256"] != _sha(body):
        raise OracleError("capsule oracle envelope digest is invalid")
    return envelope


def _capsule_ancestor_definitions(capsule: Path) -> dict[str, str]:
    capsule = _strict_canonical_path(
        capsule,
        "capsule root for process policy",
        must_exist=True,
        directory=True,
    )
    ancestors: list[Path] = []
    current = capsule.parent
    while current != current.parent:
        try:
            metadata = current.lstat()
        except OSError as error:
            raise OracleError("capsule ancestry is unavailable") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise OracleError("capsule ancestry contains a non-directory or symlink")
        ancestors.append(current)
        current = current.parent
    if len(ancestors) > CAPSULE_ANCESTOR_SLOTS:
        raise OracleError("capsule ancestry exceeds the process policy slot cap")
    padded = [*ancestors, *([capsule] * (CAPSULE_ANCESTOR_SLOTS - len(ancestors)))]
    return {f"CAPSULE_ANCESTOR_{index:02d}": str(path) for index, path in enumerate(padded)}


def _runtime_ancestor_definitions(runtime: Path) -> dict[str, str]:
    runtime = _strict_canonical_path(
        runtime,
        "runtime root for process policy",
        must_exist=True,
        directory=True,
    )
    ancestors: list[Path] = []
    current = runtime.parent
    while current != current.parent:
        try:
            metadata = current.lstat()
        except OSError as error:
            raise OracleError("runtime ancestry is unavailable") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise OracleError("runtime ancestry contains a non-directory or symlink")
        ancestors.append(current)
        current = current.parent
    if len(ancestors) > RUNTIME_ANCESTOR_SLOTS:
        raise OracleError("runtime ancestry exceeds the process policy slot cap")
    padded = [*ancestors, *([runtime] * (RUNTIME_ANCESTOR_SLOTS - len(ancestors)))]
    return {f"RUNTIME_ANCESTOR_{index:02d}": str(path) for index, path in enumerate(padded)}


def _kill_and_reap_capsule_group(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired as error:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        process.wait(timeout=2)
        raise OracleError("capsule runner group could not be reaped") from error
    deadline = time.monotonic() + 2
    while True:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        if time.monotonic() >= deadline:
            raise OracleError("capsule runner descendants remained after process-group kill")
        time.sleep(0.01)


@contextlib.contextmanager
def _secure_invocation_workspace(root: Path, name: str):
    """Create/open ``invocations/name`` without following any mutable link."""

    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,191}", name) is None:
        raise OracleError("capsule invocation workspace name is invalid")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    root_fd = -1
    invocations_fd = -1
    invocation_fd = -1
    try:
        root_fd = os.open(root, directory_flags)
        with contextlib.suppress(FileExistsError):
            os.mkdir("invocations", 0o700, dir_fd=root_fd)
        invocations_fd = os.open("invocations", directory_flags, dir_fd=root_fd)
        invocations_stat = os.fstat(invocations_fd)
        if (
            not stat.S_ISDIR(invocations_stat.st_mode)
            or stat.S_IMODE(invocations_stat.st_mode) != 0o700
        ):
            raise OracleError("capsule invocations namespace is not a private directory")
        try:
            os.stat(name, dir_fd=invocations_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise OracleError("capsule invocation workspace already exists")
        os.mkdir(name, 0o700, dir_fd=invocations_fd)
        invocation_fd = os.open(name, directory_flags, dir_fd=invocations_fd)
        metadata = os.fstat(invocation_fd)
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise OracleError("capsule invocation workspace is invalid")
        yield root / "invocations" / name, invocation_fd
    except OracleError:
        raise
    except OSError as error:
        raise OracleError("capsule invocation workspace could not be created securely") from error
    finally:
        for descriptor in (invocation_fd, invocations_fd, root_fd):
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)


@contextlib.contextmanager
def _secure_output_parent(root: Path, output: Path):
    """Open/create an output ancestry by descriptor without following aliases."""

    try:
        relative = output.relative_to(root)
    except ValueError as error:
        raise OracleError("capsule oracle output escaped the process root") from error
    if len(relative.parts) < 1 or any(part in {"", ".", ".."} for part in relative.parts):
        raise OracleError("capsule oracle output path is invalid")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    root_fd = -1
    parent_fd = -1
    try:
        root_fd = os.open(root, directory_flags)
        parent_fd = os.dup(root_fd)
        for component in relative.parts[:-1]:
            with contextlib.suppress(FileExistsError):
                os.mkdir(component, 0o700, dir_fd=parent_fd)
            child_fd = -1
            try:
                child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
                metadata = os.fstat(child_fd)
                if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
                    raise OracleError("capsule oracle output ancestry is not private")
                os.close(parent_fd)
                parent_fd = child_fd
                child_fd = -1
            finally:
                if child_fd >= 0:
                    with contextlib.suppress(OSError):
                        os.close(child_fd)
        yield parent_fd, relative.name
    except OracleError:
        raise
    except OSError as error:
        raise OracleError("capsule oracle output ancestry could not be opened securely") from error
    finally:
        for descriptor in (parent_fd, root_fd):
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)


def _publish_regular_at(directory_fd: int, name: str, raw: bytes) -> None:
    """Publish once by exclusive descriptor; retain every partial on failure."""

    if not name or "/" in name or name in {".", ".."}:
        raise OracleError("capsule oracle output filename is invalid")
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory_fd,
        )
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OracleError("capsule oracle output could not be written completely")
            view = view[written:]
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size != len(raw)
        ):
            raise OracleError("capsule oracle temporary output is invalid")
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.fsync(directory_fd)
    except OracleError:
        raise
    except OSError as error:
        raise OracleError("capsule oracle output could not be published securely") from error
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _read_exact_regular_at(directory_fd: int, name: str, limit: int, label: str) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise OracleError(f"{label} must be a bounded regular file")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise OracleError(f"{label} exceeds its cap")
        after = os.fstat(descriptor)
        identity = lambda item: (  # noqa: E731 - compact immutable stat identity
            item.st_dev,
            item.st_ino,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
            item.st_mode,
        )
        if identity(before) != identity(after) or total != before.st_size:
            raise OracleError(f"{label} changed while it was read")
        return b"".join(chunks)
    except OracleError:
        raise
    except OSError as error:
        raise OracleError(f"{label} cannot be read securely") from error
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _run_capsule_command(
    command: list[str],
    *,
    cwd: Path,
    request_bytes: bytes,
    stdout_path: Path,
    stderr_path: Path,
    timeout: float,
    node_executable: Path,
    runtime_root: Path,
    capsule_root: Path,
    process_root: Path,
    stream_directory_fd: int | None = None,
    capsule_root_fd: int | None = None,
    runtime_root_fd: int | None = None,
    node_executable_fd: int | None = None,
    process_root_fd: int | None = None,
) -> subprocess.CompletedProcess[bytes]:
    node_executable = _strict_canonical_path(
        node_executable,
        "capsule Node executable",
        must_exist=True,
        directory=False,
    )
    capsule_root = _strict_canonical_path(
        capsule_root,
        "capsule command root",
        must_exist=True,
        directory=True,
    )
    runtime_root = _strict_canonical_path(
        runtime_root,
        "capsule runtime root",
        must_exist=True,
        directory=True,
    )
    process_root = _strict_canonical_path(
        process_root,
        "capsule process root",
        must_exist=True,
        directory=True,
    )
    cwd = _strict_canonical_path(
        cwd,
        "capsule command working directory",
        must_exist=True,
        directory=True,
    )
    stdout_path = _strict_canonical_path(
        stdout_path,
        "capsule stdout path",
        must_exist=False,
        directory=False,
    )
    stderr_path = _strict_canonical_path(
        stderr_path,
        "capsule stderr path",
        must_exist=False,
        directory=False,
    )
    if (
        (
            capsule_root_fd is not None
            and not _directory_fd_matches_path(capsule_root_fd, capsule_root)
        )
        or (
            runtime_root_fd is not None
            and not _directory_fd_matches_path(runtime_root_fd, runtime_root)
        )
        or (
            process_root_fd is not None
            and not _directory_fd_matches_path(process_root_fd, process_root)
        )
        or (
            node_executable_fd is not None
            and not _file_fd_matches_path(node_executable_fd, node_executable)
        )
    ):
        raise OracleError("capsule command opened roots differ from their path identities")
    if (
        not command
        or command[0] != str(node_executable)
        or not _contains(runtime_root, node_executable)
    ):
        raise OracleError("capsule command does not start with the registered Node executable")
    if any(
        _contains(left, right)
        for left, right in (
            (runtime_root, capsule_root),
            (capsule_root, runtime_root),
            (runtime_root, process_root),
            (process_root, runtime_root),
            (capsule_root, process_root),
            (process_root, capsule_root),
        )
    ):
        raise OracleError("capsule command root classes are not disjoint")
    if (
        not _contains(capsule_root, cwd)
        or not _contains(process_root, stdout_path)
        or not _contains(process_root, stderr_path)
        or stdout_path == stderr_path
    ):
        raise OracleError("capsule command paths differ from their registered roots")
    if (
        type(timeout) not in {int, float}
        or not 0 < timeout <= 60
        or not isinstance(request_bytes, bytes)
        or len(request_bytes) > MAX_CAPSULE_FILE_BYTES
    ):
        raise OracleError("capsule command request or timeout exceeds its cap")
    measured_policy = {
        "sandbox_policy_sha256": (
            "sha256:"
            + hashlib.sha256(CAPSULE_EXECUTION_POLICY_TEMPLATE.encode("utf-8")).hexdigest()
        ),
        "capsule_ancestor_slots": CAPSULE_ANCESTOR_SLOTS,
        "runtime_ancestor_slots": RUNTIME_ANCESTOR_SLOTS,
        "process_fork": "denied",
        "supervision": "node-session-group-leader",
        "loader_flags": list(LOADER_FLAGS),
    }
    if measured_policy != CAPSULE_EXECUTION_POLICY:
        raise OracleError("capsule process policy bytes differ from their runtime identity")
    ancestor_definitions = _capsule_ancestor_definitions(capsule_root)
    ancestor_arguments = [
        argument
        for name, value in ancestor_definitions.items()
        for argument in ("-D", f"{name}={value}")
    ]
    runtime_ancestor_arguments = [
        argument
        for name, value in _runtime_ancestor_definitions(runtime_root).items()
        for argument in ("-D", f"{name}={value}")
    ]
    supervised_command = [
        str(SANDBOX_EXEC_PATH),
        "-p",
        CAPSULE_EXECUTION_POLICY_TEMPLATE,
        "-D",
        f"PROCESS_ROOT={process_root}",
        "-D",
        f"NODE_EXECUTABLE={node_executable}",
        "-D",
        f"RUNTIME_ROOT={runtime_root}",
        "-D",
        f"CAPSULE_ROOT={capsule_root}",
        *ancestor_arguments,
        *runtime_ancestor_arguments,
        *command,
    ]
    process: subprocess.Popen[bytes] | None = None
    supervision_complete = False
    stdout_descriptor = -1
    stderr_descriptor = -1
    try:
        try:
            if stream_directory_fd is None:
                stdout_descriptor = os.open(
                    stdout_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                )
                stderr_descriptor = os.open(
                    stderr_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                )
            else:
                stdout_descriptor = os.open(
                    stdout_path.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=stream_directory_fd,
                )
                stderr_descriptor = os.open(
                    stderr_path.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=stream_directory_fd,
                )
            with contextlib.ExitStack() as streams:
                stdout = streams.enter_context(os.fdopen(stdout_descriptor, "wb"))
                stdout_descriptor = -1
                stderr = streams.enter_context(os.fdopen(stderr_descriptor, "wb"))
                stderr_descriptor = -1
                if (
                    (
                        capsule_root_fd is not None
                        and not _directory_fd_matches_path(capsule_root_fd, capsule_root)
                    )
                    or (
                        runtime_root_fd is not None
                        and not _directory_fd_matches_path(runtime_root_fd, runtime_root)
                    )
                    or (
                        process_root_fd is not None
                        and not _directory_fd_matches_path(process_root_fd, process_root)
                    )
                    or (
                        node_executable_fd is not None
                        and not _file_fd_matches_path(node_executable_fd, node_executable)
                    )
                ):
                    raise OracleError("capsule command roots changed before execution")
                process = subprocess.Popen(
                    supervised_command,
                    cwd=cwd,
                    stdin=subprocess.PIPE,
                    stdout=stdout,
                    stderr=stderr,
                    env=_capsule_production_environment(),
                    start_new_session=True,
                )
                if os.getpgid(process.pid) != process.pid or os.getsid(process.pid) != process.pid:
                    _kill_and_reap_capsule_group(process)
                    supervision_complete = True
                    raise OracleError("capsule Node is not its supervised session leader")
                try:
                    process.communicate(input=request_bytes, timeout=timeout)
                except subprocess.TimeoutExpired as error:
                    _kill_and_reap_capsule_group(process)
                    supervision_complete = True
                    raise OracleError("capsule runner exceeded the timeout cap") from error
                _kill_and_reap_capsule_group(process)
                supervision_complete = True
        except OracleError:
            raise
        except (OSError, subprocess.SubprocessError) as error:
            raise OracleError("capsule runner could not start") from error
        if process is None:
            raise OracleError("capsule runner process was not created")
        process.wait(timeout=2)
        if (
            (
                capsule_root_fd is not None
                and not _directory_fd_matches_path(capsule_root_fd, capsule_root)
            )
            or (
                runtime_root_fd is not None
                and not _directory_fd_matches_path(runtime_root_fd, runtime_root)
            )
            or (
                process_root_fd is not None
                and not _directory_fd_matches_path(process_root_fd, process_root)
            )
            or (
                node_executable_fd is not None
                and not _file_fd_matches_path(node_executable_fd, node_executable)
            )
        ):
            raise OracleError("capsule command roots changed during execution")
        if stream_directory_fd is None:
            stdout = _read_exact_regular(stdout_path, MAX_CAPSULE_STDOUT_BYTES, "capsule stdout")
            stderr = _read_exact_regular(stderr_path, MAX_CAPSULE_STDERR_BYTES, "capsule stderr")
        else:
            stdout = _read_exact_regular_at(
                stream_directory_fd,
                stdout_path.name,
                MAX_CAPSULE_STDOUT_BYTES,
                "capsule stdout",
            )
            stderr = _read_exact_regular_at(
                stream_directory_fd,
                stderr_path.name,
                MAX_CAPSULE_STDERR_BYTES,
                "capsule stderr",
            )
        return subprocess.CompletedProcess(
            command, process.returncode, stdout=stdout, stderr=stderr
        )
    finally:
        cleanup_error: OracleError | None = None
        if process is not None and not supervision_complete:
            try:
                _kill_and_reap_capsule_group(process)
            except OracleError as error:
                cleanup_error = error
        for descriptor in (stdout_descriptor, stderr_descriptor):
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
        if cleanup_error is not None:
            raise cleanup_error


def _capsule_command(
    capsule: Path,
    manifest: dict[str, Any],
    runtime: dict[str, Any],
    node: Path,
) -> tuple[Path, list[str]]:
    loader = _capsule_file(
        capsule,
        _safe_capsule_path(manifest["loader"]["path"], "loader"),
        "loader",
    )
    runner = _capsule_file(
        capsule,
        _safe_capsule_path(manifest["runner"]["path"], "runner"),
        "runner",
    )
    return node, [
        str(node),
        *LOADER_FLAGS,
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
        PINNED_LOADER_SHA256,
        "--runtime-node-path",
        runtime["node_path"],
        "--node-actual-path",
        str(node),
        "--runtime-loader-path",
        runtime["loader_path"],
        "--runtime-loader-flags",
        json.dumps(list(LOADER_FLAGS), separators=(",", ":")),
        "--runtime-runner-path",
        runtime["runner_path"],
        "--runner-actual-path",
        str(runner),
        "--snapshot-identity",
        f"snapshot://{PINNED_METIS_REVISION}/{PINNED_METIS_TREE}",
        "--node-modules-sha256",
        PINNED_NODE_MODULES_SHA256,
        "--runner-sha256",
        PINNED_RUNNER_SHA256,
        "--node-binary-sha256",
        PINNED_NODE_BINARY_SHA256,
        "--oracle-policy-version",
        SANDBOX_POLICY_VERSION,
        "--oracle-policy-sha256",
        SANDBOX_POLICY_SHA256,
        "--execution-policy-sha256",
        CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"].removeprefix("sha256:"),
        "--tooling-package-sha256",
        PINNED_TOOLING_PACKAGE_SHA256,
        "--tooling-lock-sha256",
        PINNED_TOOLING_LOCK_SHA256,
    ]


def _verify_runtime_preimage_at(root_fd: int, node_fd: int) -> None:
    root_metadata = os.fstat(root_fd)
    node_metadata = os.fstat(node_fd)
    files, directories = _capsule_preimage_roster_at(root_fd)
    raw, measured_node = _read_capsule_preimage_file_at(
        root_fd,
        PurePosixPath("bin/node"),
        128 * 1024 * 1024,
        "runtime Node preimage",
    )
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_IMODE(root_metadata.st_mode) != 0o555
        or files != {"bin/node"}
        or directories != {"bin": 0o555}
        or not stat.S_ISREG(node_metadata.st_mode)
        or stat.S_IMODE(node_metadata.st_mode) != 0o555
        or node_metadata.st_nlink != 1
        or node_metadata.st_size != PINNED_NODE_BYTES
        or (node_metadata.st_dev, node_metadata.st_ino)
        != (measured_node.st_dev, measured_node.st_ino)
        or hashlib.sha256(raw).hexdigest() != PINNED_NODE_BINARY_SHA256
    ):
        raise OracleError("runtime Node preimage bytes, size, mode or roster differ from the pin")


def _materialize_runtime_preimage(
    invocation: Path,
    invocation_fd: int,
    source_node: Path,
) -> tuple[Path, Path, int, int]:
    source_raw = _read_exact_regular(
        source_node,
        128 * 1024 * 1024,
        "registered Node source",
    )
    if (
        len(source_raw) != PINNED_NODE_BYTES
        or hashlib.sha256(source_raw).hexdigest() != PINNED_NODE_BINARY_SHA256
    ):
        raise OracleError("registered Node source changed before capture")
    root_fd = -1
    bin_fd = -1
    node_fd = -1
    try:
        os.mkdir("runtime", 0o700, dir_fd=invocation_fd)
        root_fd = os.open(
            "runtime",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=invocation_fd,
        )
        bin_fd = _open_capsule_preimage_directory_at(root_fd, ("bin",), create=True)
        _write_capsule_preimage_file_at(bin_fd, "node", source_raw, 0o555)
        node_fd = os.open(
            "node",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=bin_fd,
        )
        os.fchmod(bin_fd, 0o555)
        os.fchmod(root_fd, 0o555)
        _verify_runtime_preimage_at(root_fd, node_fd)
        root = invocation / "runtime"
        node = root / "bin" / "node"
        if (
            not _directory_fd_matches_path(invocation_fd, invocation)
            or not _directory_fd_matches_path(root_fd, root)
            or not _file_fd_matches_path(node_fd, node)
        ):
            raise OracleError("runtime Node preimage namespace changed during materialization")
        return root, node, root_fd, node_fd
    except BaseException:
        for descriptor in (node_fd, bin_fd, root_fd):
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
        raise
    finally:
        if bin_fd >= 0:
            with contextlib.suppress(OSError):
                os.close(bin_fd)


@contextlib.contextmanager
def _owned_materialized_runtime_preimage(
    invocation: Path,
    invocation_fd: int,
    source_node: Path,
) -> Iterator[tuple[Path, Path, int, int]]:
    root_fd = -1
    node_fd = -1
    try:
        root, node, root_fd, node_fd = _materialize_runtime_preimage(
            invocation,
            invocation_fd,
            source_node,
        )
        yield root, node, root_fd, node_fd
    finally:
        for descriptor in (node_fd, root_fd):
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)


def run_oracle_from_capsule(
    capsule_request: Any,
    *,
    capsule_root: str | os.PathLike[str],
    process_root: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Run the exact registered Node/loader/runner closure from an immutable capsule.

    This low-level boundary deliberately has no ``metis_root`` or ``runner_path``
    override and never calls :func:`_build_isolated_snapshot` or reads Git.
    """

    _require_protected_execution_broker()
    request = _validate_capsule_request(capsule_request)
    if type(timeout) not in {int, float} or not 0 < timeout <= 60:
        raise OracleError("capsule oracle timeout is outside the registered cap")
    capsule, manifest = verify_runtime_capsule(
        capsule_root,
        expected_manifest_sha256=request["capsule_manifest_sha256"],
    )
    root = _strict_canonical_path(
        process_root,
        "capsule process root",
        must_exist=True,
        directory=True,
    )
    output = _strict_canonical_path(
        output_path,
        "capsule oracle output",
        must_exist=False,
        directory=False,
    )
    if not _contains(root, output):
        raise OracleError("capsule oracle output must stay below the process root")
    _reject_symlink_parents(output, "capsule oracle output")
    invocation_name = f"{request['execution_id']}-{request['run_nonce'][:16]}"

    capsule_contents = _capture_runtime_capsule_contents(capsule, manifest)
    runtime = _runtime_identity_policy(
        PINNED_METIS_REVISION,
        PINNED_METIS_TREE,
        execution_policy_sha256=CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"],
    )
    node_source, _ = _resolve_pinned_node()
    semantic = request["request"]
    with (
        _secure_invocation_workspace(root, invocation_name) as (invocation, invocation_fd),
        _owned_materialized_runtime_capsule_preimage(
            invocation,
            invocation_fd,
            manifest,
            capsule_contents,
        ) as (capsule_preimage, capsule_preimage_fd),
        _owned_materialized_runtime_preimage(
            invocation,
            invocation_fd,
            node_source,
        ) as (runtime_root, runtime_node, runtime_fd, runtime_node_fd),
    ):
        write_fd = -1
        try:
            os.mkdir("write", 0o700, dir_fd=invocation_fd)
            write_fd = os.open(
                "write",
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=invocation_fd,
            )
            write_root = invocation / "write"
            write_metadata = os.fstat(write_fd)
            if (
                not stat.S_ISDIR(write_metadata.st_mode)
                or stat.S_IMODE(write_metadata.st_mode) != 0o700
            ):
                raise OracleError("capsule writable invocation root is invalid")
            node, command = _capsule_command(
                capsule_preimage,
                manifest,
                runtime,
                runtime_node,
            )
            completed = _run_capsule_command(
                command,
                cwd=capsule_preimage / "tooling",
                request_bytes=_canonical(semantic),
                stdout_path=write_root / "stdout.json",
                stderr_path=write_root / "stderr.txt",
                timeout=float(timeout),
                node_executable=node,
                runtime_root=runtime_root,
                capsule_root=capsule_preimage,
                process_root=write_root,
                stream_directory_fd=write_fd,
                capsule_root_fd=capsule_preimage_fd,
                runtime_root_fd=runtime_fd,
                node_executable_fd=runtime_node_fd,
                process_root_fd=write_fd,
            )
            _verify_runtime_preimage_at(runtime_fd, runtime_node_fd)
            _verify_runtime_capsule_preimage_at(
                capsule_preimage_fd,
                manifest,
                capsule_contents,
            )
            if not _directory_fd_matches_path(capsule_preimage_fd, capsule_preimage):
                raise OracleError("runtime capsule preimage path changed during execution")
        except OracleError:
            raise
        except OSError as error:
            raise OracleError("capsule invocation roots could not be created securely") from error
        finally:
            if write_fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(write_fd)
    if completed.returncode != 0:
        raise OracleError(f"capsule runner exited {completed.returncode}")
    if completed.stderr:
        raise OracleError("capsule runner emitted unregistered stderr")
    try:
        result = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OracleError("capsule runner emitted malformed JSON") from error
    if completed.stdout != _canonical(result):
        raise OracleError("capsule runner output is not canonical JSON")
    result = _check_response(
        result,
        PINNED_METIS_REVISION,
        PINNED_METIS_TREE,
        expected_runtime=runtime,
        expected_mode=semantic["execution_mode"],
    )
    evidence = {
        "input_sha256": _sha(semantic),
        "diagnostics_sha256": _sha(result["diagnostics"]),
        "ast_sha256": _sha(result["ast"]["inventory"]),
        "ir_sha256": None if result["ir"]["value"] is None else _sha(result["ir"]["value"]),
        "toolchain_revision": PINNED_METIS_REVISION,
        "toolchain_tree": PINNED_METIS_TREE,
        "runtime_sha256": _sha(runtime),
        "runtime_identity": runtime,
        "runner_sha256": "sha256:" + PINNED_RUNNER_SHA256,
        "loader_sha256": "sha256:" + PINNED_LOADER_SHA256,
        "tooling_package_sha256": "sha256:" + PINNED_TOOLING_PACKAGE_SHA256,
        "tooling_lock_sha256": "sha256:" + PINNED_TOOLING_LOCK_SHA256,
        "node_modules_sha256": "sha256:" + PINNED_NODE_MODULES_SHA256,
        "node_binary_sha256": "sha256:" + PINNED_NODE_BINARY_SHA256,
        "oracle_policy_sha256": runtime["oracle_policy_sha256"],
        "execution_policy_sha256": runtime["execution_policy_sha256"],
        "metis_status_sha256": _sha(""),
        "metis_status": "",
    }
    oracle_envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "result": result,
        "evidence": evidence,
    }
    oracle_envelope["evidence"]["envelope_sha256"] = _sha(oracle_envelope)
    verify_oracle_envelope(
        oracle_envelope,
        request=semantic,
        expected_execution_policy_sha256=CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"],
    )
    capsule_body = {
        "schema_version": CAPSULE_SCHEMA_VERSION,
        "protocol": CAPSULE_PROTOCOL,
        "execution_id": request["execution_id"],
        "request_sha256": _sha(semantic),
        "capsule_manifest_sha256": request["capsule_manifest_sha256"],
        "execution_policy": dict(CAPSULE_EXECUTION_POLICY),
        "oracle_envelope": oracle_envelope,
    }
    envelope = {
        **capsule_body,
        "run_nonce": request["run_nonce"],
        "manifest_sha256": _sha(capsule_body),
    }
    verify_capsule_oracle_envelope(envelope, capsule_request=request)
    with _secure_output_parent(root, output) as (output_parent_fd, output_name):
        _publish_regular_at(output_parent_fd, output_name, _canonical(envelope))
    return envelope


class OracleSession:
    """Explicit process-private reuse of one fully pinned old-oracle snapshot."""

    def __init__(
        self,
        *,
        metis_root: str | os.PathLike[str],
        runner_path: str | os.PathLike[str],
        expected_revision: str = PINNED_METIS_REVISION,
    ) -> None:
        self._metis_root_argument = metis_root
        self._runner_argument = runner_path
        self._expected_revision = expected_revision
        self._creator_pid: int | None = None
        self._entered = False
        self._closed = False
        self._poisoned = False
        self._poison_error: BaseException | None = None
        self._run_lock = threading.Lock()
        self._holder: tempfile.TemporaryDirectory[str] | None = None
        self._root: Path | None = None
        self._source_modules: Path | None = None
        self._runner: Path | None = None
        self._node: Path | None = None
        self._snapshot: Path | None = None
        self._snapshot_modules: Path | None = None
        self._snapshot_runner: Path | None = None
        self._snapshot_loader: Path | None = None
        self._snapshot_node: Path | None = None
        self._revision: str | None = None
        self._tree: str | None = None
        self._toolchain_runtime: dict[str, str] | None = None
        self._runtime: dict[str, Any] | None = None
        self._source_status: str | None = None
        self._root_fd = -1
        self._source_modules_fd = -1
        self._snapshot_fd = -1
        self._snapshot_modules_fd = -1
        self._source_modules_roster: tuple[tuple[Any, ...], ...] | None = None
        self._snapshot_roster: tuple[tuple[Any, ...], ...] | None = None
        self._file_identities: tuple[tuple[Path, str, tuple[int, ...], str], ...] = ()
        self._global_identity: tuple[Any, ...] | None = None
        self._node_resolution_environment: tuple[str | None, str | None] | None = None

    def __enter__(self) -> OracleSession:
        if self._entered or self._closed:
            raise OracleError("oracle session instances are single-use")
        self._creator_pid = os.getpid()
        try:
            _assert_sandbox_policy()
            root, revision, tree, toolchain_runtime = validate_pinned_metis(
                self._metis_root_argument,
                expected_revision=self._expected_revision,
            )
            runner = _validate_runner_path(self._runner_argument, root)
            node, node_binary_sha256 = _resolve_pinned_node()
            runtime = _runtime_identity(
                PINNED_NODE_VERSION,
                node_binary_sha256,
                revision,
                tree,
                toolchain_runtime,
            )
            source_status = _git(root, "status", "--porcelain=v1", "--untracked-files=no")
            if (
                _git(root, "rev-parse", "HEAD") != revision
                or _git(root, "rev-parse", "HEAD^{tree}") != tree
            ):
                raise OracleError("Metis checkout changed during validation")
            source_modules = (root / "tooling" / "node_modules").resolve(strict=True)
            (
                holder,
                snapshot,
                snapshot_modules,
                snapshot_runner,
                snapshot_loader,
                snapshot_node,
            ) = _build_isolated_snapshot(
                root,
                revision,
                tree,
                toolchain_runtime,
                runner,
                node,
            )
            self._holder = holder
            self._root = root
            self._source_modules = source_modules
            self._runner = runner
            self._node = node
            self._snapshot = snapshot
            self._snapshot_modules = snapshot_modules
            self._snapshot_runner = snapshot_runner
            self._snapshot_loader = snapshot_loader
            self._snapshot_node = snapshot_node
            self._revision = revision
            self._tree = tree
            self._toolchain_runtime = toolchain_runtime
            self._runtime = runtime
            self._source_status = source_status
            self._root_fd = _open_metadata_directory(root, "Metis root")
            self._source_modules_fd = _open_metadata_directory(
                source_modules, "Metis tooling runtime"
            )
            self._snapshot_fd = _open_metadata_directory(snapshot, "oracle snapshot")
            self._snapshot_modules_fd = _open_metadata_directory(
                snapshot_modules, "isolated tooling runtime"
            )
            self._source_modules_roster = _directory_metadata_roster(self._source_modules_fd)
            self._snapshot_roster = _directory_metadata_roster(self._snapshot_fd)
            if _node_modules_sha256(source_modules) != toolchain_runtime["node_modules_sha256"]:
                raise OracleError("Metis tooling node_modules changed during session setup")
            if _node_modules_sha256(snapshot_modules) != toolchain_runtime["node_modules_sha256"]:
                raise OracleError("isolated tooling node_modules changed before execution")
            guarded_files = (
                (
                    root / "tooling" / "package.json",
                    "source tooling package",
                    toolchain_runtime["package_sha256"],
                    "Metis tooling package.json changed during session setup",
                ),
                (
                    root / "tooling" / "package-lock.json",
                    "source tooling lock",
                    toolchain_runtime["lock_sha256"],
                    "Metis tooling package-lock.json changed during session setup",
                ),
                (
                    snapshot / "tooling" / "package.json",
                    "isolated tooling package",
                    toolchain_runtime["package_sha256"],
                    "isolated tooling package.json changed before execution",
                ),
                (
                    snapshot / "tooling" / "package-lock.json",
                    "isolated tooling lock",
                    toolchain_runtime["lock_sha256"],
                    "isolated tooling package-lock.json changed before execution",
                ),
                (runner, "source oracle runner", PINNED_RUNNER_SHA256, "source runner changed"),
                (
                    LOADER_PATH,
                    "source native loader",
                    PINNED_LOADER_SHA256,
                    "source native loader changed",
                ),
                (
                    node,
                    "source Node binary",
                    PINNED_NODE_BINARY_SHA256,
                    "source Node binary changed during session setup",
                ),
                (
                    snapshot_runner,
                    "isolated oracle runner",
                    PINNED_RUNNER_SHA256,
                    "isolated runner changed before execution",
                ),
                (
                    snapshot_loader,
                    "isolated native loader",
                    PINNED_LOADER_SHA256,
                    "isolated native loader changed before execution",
                ),
                (
                    snapshot_node,
                    "isolated Node binary",
                    PINNED_NODE_BINARY_SHA256,
                    "isolated Node binary changed before execution",
                ),
                (SANDBOX_EXEC_PATH, "sandbox executable", None, None),
                (SCHEMA_PATH, "oracle result schema", None, None),
            )
            file_identities: list[tuple[Path, str, tuple[int, ...], str]] = []
            for path, label, expected_digest, mismatch_message in guarded_files:
                identity = _regular_file_metadata(path, label)
                digest = _file_sha256(path)
                if expected_digest is not None and digest != expected_digest:
                    raise OracleError(mismatch_message or f"{label} changed")
                file_identities.append((path, label, identity, digest))
            self._file_identities = tuple(file_identities)
            self._global_identity = _oracle_session_global_identity()
            self._node_resolution_environment = (
                os.environ.get(NODE_RUNTIME_ENV),
                os.environ.get("PATH"),
            )
            self._entered = True
            self._assert_metadata_unchanged()
            return self
        except BaseException:
            self._cleanup()
            raise

    def _require_active(self) -> None:
        if not self._entered or self._closed:
            raise OracleError("oracle session is not active")
        if os.getpid() != self._creator_pid:
            raise OracleError("oracle session cannot cross a process boundary")
        if self._poisoned:
            raise OracleError("oracle session is poisoned by authority drift")

    def _assert_process_binding(self) -> None:
        if os.getpid() != self._creator_pid:
            raise OracleError("oracle session cannot cross a process boundary")
        if _oracle_session_global_identity() != self._global_identity:
            raise OracleError("oracle session process authority changed")
        if (
            os.environ.get(NODE_RUNTIME_ENV),
            os.environ.get("PATH"),
        ) != self._node_resolution_environment:
            raise OracleError("oracle session Node resolution environment changed")

    def _assert_metadata_unchanged(self) -> None:
        self._assert_process_binding()
        if (
            self._root is None
            or self._source_modules is None
            or self._snapshot is None
            or self._snapshot_modules is None
            or self._revision is None
            or self._tree is None
            or self._source_status is None
            or self._source_modules_roster is None
            or self._snapshot_roster is None
        ):
            raise OracleError("oracle session authority is incomplete")
        directory_bindings = (
            (self._root_fd, self._root, "Metis root"),
            (self._source_modules_fd, self._source_modules, "Metis tooling runtime"),
            (self._snapshot_fd, self._snapshot, "oracle snapshot"),
            (
                self._snapshot_modules_fd,
                self._snapshot_modules,
                "isolated tooling runtime",
            ),
        )
        if any(
            descriptor < 0 or not _directory_fd_matches_path(descriptor, path)
            for descriptor, path, _label in directory_bindings
        ):
            raise OracleError("oracle session authority directory identity changed")
        if _directory_metadata_roster(self._source_modules_fd) != self._source_modules_roster:
            raise OracleError("oracle session source tooling metadata changed")
        if _directory_metadata_roster(self._snapshot_fd) != self._snapshot_roster:
            raise OracleError("oracle session isolated tooling metadata changed")
        for path, label, identity, _digest in self._file_identities:
            if _regular_file_metadata(path, label) != identity:
                raise OracleError(f"oracle session {label} metadata changed")
        if (
            _git(self._root, "status", "--porcelain=v1", "--untracked-files=no")
            != self._source_status
            or _git(self._root, "rev-parse", "HEAD") != self._revision
            or _git(self._root, "rev-parse", "HEAD^{tree}") != self._tree
        ):
            raise OracleError("oracle session Metis checkout identity changed")

    def _guard_authority(self) -> None:
        try:
            self._assert_metadata_unchanged()
        except BaseException as error:
            self._poisoned = True
            if self._poison_error is None:
                self._poison_error = error
            raise

    def _assert_full_unchanged(self) -> None:
        self._assert_metadata_unchanged()
        if (
            self._source_modules is None
            or self._snapshot_modules is None
            or self._toolchain_runtime is None
        ):
            raise OracleError("oracle session authority is incomplete")
        modules_pin = self._toolchain_runtime["node_modules_sha256"]
        if _node_modules_sha256(self._source_modules) != modules_pin:
            raise OracleError("oracle session source tooling content changed")
        if _node_modules_sha256(self._snapshot_modules) != modules_pin:
            raise OracleError("oracle session isolated tooling content changed")
        for path, label, _identity, digest in self._file_identities:
            if _file_sha256(path) != digest:
                raise OracleError(f"oracle session {label} content changed")
        self._assert_metadata_unchanged()

    def _guard_full_authority(self) -> None:
        try:
            self._assert_full_unchanged()
        except BaseException as error:
            self._poisoned = True
            if self._poison_error is None:
                self._poison_error = error
            raise

    def _cleanup(self) -> None:
        for attribute in (
            "_snapshot_modules_fd",
            "_snapshot_fd",
            "_source_modules_fd",
            "_root_fd",
        ):
            descriptor = getattr(self, attribute)
            setattr(self, attribute, -1)
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
        holder = self._holder
        self._holder = None
        if holder is not None:
            holder.cleanup()
        self._closed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> bool:
        del exc_type, traceback
        if self._closed:
            return False
        if os.getpid() != self._creator_pid:
            raise OracleError("oracle session cannot be closed across a process boundary")
        if not self._run_lock.acquire(blocking=False):
            raise OracleError("oracle session cannot close during an active request")
        close_error: BaseException | None = None
        try:
            try:
                self._assert_full_unchanged()
            except BaseException as error:
                self._poisoned = True
                if self._poison_error is None:
                    self._poison_error = error
                close_error = error
        finally:
            self._run_lock.release()
            try:
                self._cleanup()
            except BaseException as error:
                if close_error is None:
                    close_error = error
        if exc is not None:
            if close_error is not None and hasattr(exc, "add_note"):
                exc.add_note(f"oracle session close also failed: {close_error}")
            return False
        if close_error is not None:
            raise close_error
        if self._poison_error is not None:
            raise self._poison_error
        return False

    def run(
        self,
        source: str,
        *,
        output_path: str | os.PathLike[str] | None = None,
        output_dir: str | os.PathLike[str] | None = None,
        filename: str = "oracle.metis",
        execution_mode: str = "endpoint",
        endpoint: str | None = None,
        workspace_sources: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Run through a fresh sandboxed Node process.

        A result returned without an output target remains provisional until
        this session closes cleanly.  A requested durable output is guarded by
        a full content check immediately before publication.
        """

        self._require_active()
        if not self._run_lock.acquire(blocking=False):
            raise OracleError("oracle session requests must be sequential")
        try:
            try:
                self._assert_process_binding()
            except BaseException as error:
                self._poisoned = True
                if self._poison_error is None:
                    self._poison_error = error
                raise
            if (
                self._root is None
                or self._snapshot is None
                or self._snapshot_runner is None
                or self._snapshot_loader is None
                or self._snapshot_node is None
                or self._revision is None
                or self._tree is None
                or self._toolchain_runtime is None
                or self._runtime is None
                or self._source_status is None
            ):
                raise OracleError("oracle session authority is incomplete")
            build_oracle_request(
                source,
                filename=filename,
                execution_mode=execution_mode,
                endpoint=endpoint,
                workspace_sources=workspace_sources,
                revision=self._revision,
                tree=self._tree,
            )
            if output_path is not None and output_dir is not None:
                raise OracleError("provide output_path or output_dir, not both")
            output: Path | None = None
            if output_dir is not None:
                directory = _resolve_absolute(output_dir or "", "output_dir")
                if _contains(self._root, directory):
                    raise OracleError("output_dir may not be inside the Metis checkout")
                output = _validate_output_path(directory / "oracle-result.json", self._root)
            elif output_path is not None:
                output = _validate_output_path(output_path, self._root)
            if output is not None:
                output.parent.mkdir(parents=True, exist_ok=True)
            request = build_oracle_request(
                source,
                filename=filename,
                execution_mode=execution_mode,
                endpoint=endpoint,
                workspace_sources=workspace_sources,
                revision=self._revision,
                tree=self._tree,
            )
            request_bytes = _canonical(request)
            self._guard_authority()
            snapshot_identity = f"snapshot://{self._revision}/{self._tree}"
            command = [
                str(self._snapshot_node),
                *LOADER_FLAGS,
                str(self._snapshot_loader),
                str(self._snapshot_runner),
                "--metis-root",
                str(self._snapshot),
                "--metis-revision",
                self._revision,
                "--metis-tree",
                self._tree,
                "--loader-path",
                str(self._snapshot_loader),
                "--loader-sha256",
                PINNED_LOADER_SHA256,
                "--runtime-node-path",
                self._runtime["node_path"],
                "--node-actual-path",
                str(self._snapshot_node.resolve()),
                "--runtime-loader-path",
                self._runtime["loader_path"],
                "--runtime-loader-flags",
                json.dumps(list(LOADER_FLAGS), separators=(",", ":")),
                "--runtime-runner-path",
                self._runtime["runner_path"],
                "--runner-actual-path",
                str(self._snapshot_runner),
                "--snapshot-identity",
                snapshot_identity,
                "--node-modules-sha256",
                self._toolchain_runtime["node_modules_sha256"],
                "--runner-sha256",
                PINNED_RUNNER_SHA256,
                "--node-binary-sha256",
                PINNED_NODE_BINARY_SHA256,
                "--oracle-policy-version",
                SANDBOX_POLICY_VERSION,
                "--oracle-policy-sha256",
                SANDBOX_POLICY_SHA256,
                "--execution-policy-sha256",
                SANDBOX_POLICY_SHA256,
                "--tooling-package-sha256",
                self._toolchain_runtime["package_sha256"],
                "--tooling-lock-sha256",
                self._toolchain_runtime["lock_sha256"],
            ]
            sandbox_command = [str(SANDBOX_EXEC_PATH), "-p", SANDBOX_POLICY, *command]
            completed: subprocess.CompletedProcess[str] | None = None
            launch_error: Exception | None = None
            try:
                try:
                    completed = subprocess.run(
                        sandbox_command,
                        cwd=self._snapshot / "tooling",
                        input=request_bytes.decode("utf-8"),
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        check=False,
                        env=STERILE_ENV,
                    )
                except (OSError, subprocess.SubprocessError) as error:
                    launch_error = error
            finally:
                self._guard_authority()
            if launch_error is not None:
                raise OracleError(
                    f"oracle runner failed to start: {launch_error}"
                ) from launch_error
            if completed is None:
                raise OracleError("oracle runner produced no process result")
            if completed.returncode != 0:
                raise OracleError(
                    f"oracle runner exited {completed.returncode}: {completed.stderr.strip()[:500]}"
                )
            try:
                result = json.loads(completed.stdout)
            except json.JSONDecodeError as error:
                raise OracleError("oracle runner emitted malformed JSON") from error
            if completed.stdout.strip() != _canonical(result).decode("utf-8"):
                raise OracleError("oracle runner output is not canonical JSON")
            result = _check_response(
                result,
                self._revision,
                self._tree,
                expected_runtime=self._runtime,
                expected_mode=execution_mode,
            )
            evidence = {
                "input_sha256": _sha(request),
                "diagnostics_sha256": _sha(result["diagnostics"]),
                "ast_sha256": _sha(result["ast"]["inventory"]),
                "ir_sha256": (
                    None if result["ir"]["value"] is None else _sha(result["ir"]["value"])
                ),
                "toolchain_revision": self._revision,
                "toolchain_tree": self._tree,
                "runtime_sha256": _sha(self._runtime),
                "runtime_identity": copy.deepcopy(self._runtime),
                "runner_sha256": "sha256:" + PINNED_RUNNER_SHA256,
                "loader_sha256": "sha256:" + PINNED_LOADER_SHA256,
                "tooling_package_sha256": ("sha256:" + self._toolchain_runtime["package_sha256"]),
                "tooling_lock_sha256": "sha256:" + self._toolchain_runtime["lock_sha256"],
                "node_modules_sha256": ("sha256:" + self._toolchain_runtime["node_modules_sha256"]),
                "node_binary_sha256": "sha256:" + PINNED_NODE_BINARY_SHA256,
                "oracle_policy_sha256": self._runtime["oracle_policy_sha256"],
                "execution_policy_sha256": self._runtime["execution_policy_sha256"],
                "metis_status_sha256": _sha(self._source_status),
                "metis_status": self._source_status,
            }
            envelope: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "result": result,
                "evidence": evidence,
            }
            envelope["evidence"]["envelope_sha256"] = _sha(envelope)
            verify_oracle_envelope(envelope, request=request)
            if output is None:
                return envelope
            self._guard_full_authority()
            payload = _canonical(envelope)
            with tempfile.NamedTemporaryFile(
                "wb", dir=output.parent, prefix=f".{output.name}.", delete=False
            ) as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
                temporary = Path(tmp.name)
            try:
                os.replace(temporary, output)
                directory_fd = -1
                try:
                    directory_fd = os.open(output.parent, os.O_RDONLY)
                    os.fsync(directory_fd)
                finally:
                    if directory_fd >= 0:
                        with contextlib.suppress(OSError):
                            os.close(directory_fd)
            finally:
                temporary.unlink(missing_ok=True)
            return envelope
        finally:
            self._run_lock.release()


def run_oracle(
    source: str,
    *,
    metis_root: str | os.PathLike[str],
    runner_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    filename: str = "oracle.metis",
    execution_mode: str = "endpoint",
    endpoint: str | None = None,
    workspace_sources: dict[str, str] | None = None,
    timeout: float = 60.0,
    expected_revision: str = PINNED_METIS_REVISION,
) -> dict[str, Any]:
    """Execute one request through an isolated one-shot :class:`OracleSession`."""

    build_oracle_request(
        source,
        filename=filename,
        execution_mode=execution_mode,
        endpoint=endpoint,
        workspace_sources=workspace_sources,
    )
    if output_path is not None and output_dir is not None:
        raise OracleError("provide output_path or output_dir, not both")
    if output_path is None and output_dir is None:
        raise OracleError("an output path is required")
    try:
        output_root = _resolve_absolute(metis_root, "metis_root").resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise OracleError("metis_root must be an existing directory") from error
    if not output_root.is_dir():
        raise OracleError("metis_root must be an existing directory")
    if output_path is None:
        directory = _resolve_absolute(output_dir or "", "output_dir")
        if _contains(output_root, directory):
            raise OracleError("output_dir may not be inside the Metis checkout")
        output_path = directory / "oracle-result.json"
    prevalidated_output = _validate_output_path(output_path, output_root)
    with OracleSession(
        metis_root=metis_root,
        runner_path=runner_path,
        expected_revision=expected_revision,
    ) as session:
        return session.run(
            source,
            output_path=prevalidated_output,
            filename=filename,
            execution_mode=execution_mode,
            endpoint=endpoint,
            workspace_sources=workspace_sources,
            timeout=timeout,
        )


run_metis_oracle = run_oracle
execute_oracle = run_oracle
