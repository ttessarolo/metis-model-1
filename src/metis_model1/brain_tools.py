"""Pinned, snapshot-only Metis compiler and semantic projection bridge.

Both tools consume the immutable snapshot captured when a Brain session opens.
The live tenant is never passed to Node and is never written: Python
materializes a private copy inside an archive of the exact Metis Brain pin,
executes one repository-owned runner with network and writes denied, and
returns either a redacted compiler receipt or a normalized schema-2 projection.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from metis_model1 import brain_toolchain_pin as brain_pin
from metis_model1 import catalog_maintenance_pin as sandbox_support
from metis_model1.brain_context import ContextSnapshot, toolchain_binding_from_pin
from metis_model1.brain_protocol import BrainError, bounded_source, canonical_json, canonical_sha256
from metis_model1.brain_semantic_retrieval import LoadedProjection
from metis_model1.brain_sessions import OperationLease
from metis_model1.video_catalog_projection import (
    VideoCatalogProjectionError,
    build_catalog_semantic_projection,
    validate_catalog_projection_receipt,
)

_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\.metis$")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = PROJECT_ROOT / "runtime/metis_brain/runner.mts"
RUNNER_SHA256 = "sha256:0a8d5a1962a391baf7a348115e2d9959316c6e1655281192f66f2c791666601e"
MAX_RUNNER_BYTES = 256 * 1024
MAX_RUNNER_STDOUT_BYTES = 32 * 1024 * 1024
MAX_RUNNER_STDERR_BYTES = 128 * 1024
MAX_SNAPSHOT_FILES = 1024
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
RUNNER_TIMEOUT_SECONDS = 180


class _BrainIsolationError(RuntimeError):
    pass


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _stable_regular_bytes(path: Path, *, label: str, maximum: int) -> bytes:
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_size > maximum:
            raise _BrainIsolationError(f"{label} is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = opened.st_size + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        named_after = path.lstat()
    except _BrainIsolationError:
        raise
    except OSError as error:
        raise _BrainIsolationError(f"{label} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if (
        _stat_identity(before) != _stat_identity(opened)
        or _stat_identity(opened) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(named_after)
        or len(raw) != opened.st_size
    ):
        raise _BrainIsolationError(f"{label} changed while it was read")
    return raw


def _runner_bytes() -> bytes:
    raw = _stable_regular_bytes(RUNNER_PATH, label="Brain runner", maximum=MAX_RUNNER_BYTES)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if digest != RUNNER_SHA256:
        raise _BrainIsolationError("Brain runner differs from its fixed digest")
    return raw


def _brain_pin_identity(
    metis_root: Path,
    node_path: Path,
) -> tuple[dict[str, Any], tuple[str, str, str]]:
    """Verify current Git objects/runtime and bind the repository-owned runner."""

    if brain_pin.validate_metis_brain_toolchain_pin_contract():
        raise _BrainIsolationError("Metis Brain toolchain pin is invalid")
    _runner_bytes()
    try:
        verified = brain_pin.verify_metis_brain_toolchain_pin(metis_root, node_path)
    except (brain_pin.BrainToolchainPinError, OSError) as error:
        raise _BrainIsolationError("pinned Metis authority is unavailable") from error
    identity = verified.get("identity")
    if not isinstance(identity, brain_pin.BrainToolchainIdentity):
        raise _BrainIsolationError("pinned Metis identity is unavailable")
    pin_identity = identity.as_dict()
    pin_identity["runner_sha256"] = RUNNER_SHA256
    return pin_identity, (
        identity.revision,
        identity.tree,
        identity.node_modules_sha256.removeprefix("sha256:"),
    )


@contextmanager
def _isolated_metis_repository(
    *,
    metis_root: Path,
    node_path: Path,
    expected_identity: tuple[str, str, str],
) -> Iterator[Path]:
    """Materialize one clean Git archive plus hash-checked Node dependencies."""

    manifest = brain_pin.load_metis_brain_toolchain_pin()
    root = Path(metis_root).resolve(strict=True)
    before_pin, before_identity = _brain_pin_identity(root, node_path)
    if before_identity != expected_identity:
        raise _BrainIsolationError("Metis authority changed before isolation")
    del before_pin
    runner = _runner_bytes()
    node_bytes = brain_pin._verify_node(node_path, manifest["runtime"])
    archive = brain_pin._git(
        root,
        "archive",
        "--format=tar",
        manifest["revision"],
        text=False,
    )
    if not isinstance(archive, bytes):
        raise _BrainIsolationError("pinned Git archive is unavailable")
    source_modules = (root / "tooling/node_modules").resolve(strict=True)
    if brain_pin._node_modules_sha256(source_modules) != expected_identity[2]:
        raise _BrainIsolationError("tooling runtime changed before copy")
    try:
        with tempfile.TemporaryDirectory(prefix="metis-brain-authority-") as temporary:
            isolated = Path(temporary) / "metis"
            isolated.mkdir(mode=0o700)
            sandbox_support._safe_extract_archive(archive, isolated)
            snapshot_modules = isolated / "tooling/node_modules"
            shutil.copytree(source_modules, snapshot_modules, symlinks=True)
            if (
                brain_pin._node_modules_sha256(snapshot_modules) != expected_identity[2]
                or brain_pin._node_modules_sha256(source_modules) != expected_identity[2]
            ):
                raise _BrainIsolationError("copied tooling runtime differs from pin")
            runner_target = isolated / "runtime/metis_brain/runner.mts"
            runner_target.parent.mkdir(parents=True, mode=0o700)
            runner_target.write_bytes(runner)
            if (
                _stable_regular_bytes(
                    runner_target,
                    label="isolated Brain runner",
                    maximum=MAX_RUNNER_BYTES,
                )
                != runner
            ):
                raise _BrainIsolationError("isolated Brain runner differs from pin")
            yield isolated
    except (
        brain_pin.BrainToolchainPinError,
        sandbox_support.CatalogMaintenancePinError,
        OSError,
        shutil.Error,
    ) as error:
        if isinstance(error, _BrainIsolationError):
            raise
        raise _BrainIsolationError("cannot construct isolated Metis authority") from error
    finally:
        try:
            if brain_pin._verify_node(node_path, manifest["runtime"]) != node_bytes:
                raise _BrainIsolationError("Node authority changed during isolation")
            if _runner_bytes() != runner:
                raise _BrainIsolationError("Brain runner changed during isolation")
            _after_pin, after_identity = _brain_pin_identity(root, node_path)
            if after_identity != expected_identity:
                raise _BrainIsolationError("Metis authority changed during isolation")
        except (brain_pin.BrainToolchainPinError, OSError) as error:
            raise _BrainIsolationError("Metis authority changed during isolation") from error


def _safe_relative(value: Any, *, label: str, metis_only: bool = False) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise _BrainIsolationError(f"{label} is not a safe relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", "..", ".git"} or part.startswith(".env") for part in path.parts)
        or (metis_only and value != "metis.toml" and path.suffix != ".metis")
    ):
        raise _BrainIsolationError(f"{label} is not a safe relative POSIX path")
    return path


def _materialize_snapshot(
    snapshot: ContextSnapshot,
    isolated_root: Path,
    *,
    candidate_filename: str | None = None,
    candidate_source: str | None = None,
) -> Path:
    files = snapshot.files
    if not isinstance(files, tuple) or not files or len(files) > MAX_SNAPSHOT_FILES:
        raise _BrainIsolationError("snapshot file roster is invalid")
    destination = isolated_root / "brain-tenant"
    destination.mkdir(mode=0o700)
    seen: set[str] = set()
    total = 0
    for item in files:
        relative = _safe_relative(item.path, label="snapshot path", metis_only=True)
        path_text = relative.as_posix()
        if path_text in seen:
            raise _BrainIsolationError("snapshot contains duplicate paths")
        seen.add(path_text)
        if path_text == candidate_filename:
            continue
        raw = item.content
        if not isinstance(raw, bytes):
            raise _BrainIsolationError("snapshot source is invalid")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise _BrainIsolationError("snapshot source is not UTF-8") from error
        if "sha256:" + hashlib.sha256(raw).hexdigest() != item.sha256:
            raise _BrainIsolationError("snapshot source hash differs")
        total += len(raw)
        if total > MAX_SNAPSHOT_BYTES:
            raise _BrainIsolationError("snapshot exceeds the byte limit")
        target = destination / Path(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    if "metis.toml" not in seen:
        raise _BrainIsolationError("snapshot has no metis.toml")
    if candidate_filename is not None:
        if candidate_source is None:
            raise _BrainIsolationError("candidate source is missing")
        relative = _safe_relative(candidate_filename, label="candidate path", metis_only=True)
        raw = candidate_source.encode("utf-8")
        total += len(raw)
        if total > MAX_SNAPSHOT_BYTES:
            raise _BrainIsolationError("candidate snapshot exceeds the byte limit")
        target = destination / Path(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return destination


def _sandbox_policy(isolated_root: Path, node_path: Path) -> str:
    if not isolated_root.is_absolute() or not node_path.is_absolute():
        raise _BrainIsolationError("sandbox paths must be absolute")
    return " ".join(
        (
            sandbox_support._sandbox_policy(isolated_root),
            f"(allow file-read* (literal {json.dumps(str(node_path))}))",
        )
    )


def _parse_runner_response(raw: bytes) -> dict[str, Any]:
    def duplicate_guard(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _BrainIsolationError("Brain runner returned duplicate fields")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise _BrainIsolationError("Brain runner returned a non-JSON number")

    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=duplicate_guard,
            parse_constant=reject_constant,
        )
    except _BrainIsolationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise _BrainIsolationError("Brain runner returned invalid JSON") from error
    if not isinstance(parsed, dict):
        raise _BrainIsolationError("Brain runner response is not an object")
    return parsed


def _run_brain_runner(
    *,
    isolated_root: Path,
    node_path: Path,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    policy = _sandbox_policy(isolated_root, node_path)
    sandbox_support._assert_sandbox_boundaries(isolated_root, policy)
    command = [
        str(sandbox_support.SANDBOX_EXEC),
        "-p",
        policy,
        str(node_path),
        "--import",
        "tsx",
        str(isolated_root / "runtime/metis_brain/runner.mts"),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=isolated_root / "tooling",
            input=canonical_json(dict(request)),
            capture_output=True,
            check=False,
            timeout=RUNNER_TIMEOUT_SECONDS,
            env=sandbox_support._probe_process_environment(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise _BrainIsolationError("Brain runner could not execute") from error
    if len(completed.stdout) > MAX_RUNNER_STDOUT_BYTES:
        raise _BrainIsolationError("Brain runner output exceeds its limit")
    if len(completed.stderr) > MAX_RUNNER_STDERR_BYTES:
        raise _BrainIsolationError("Brain runner diagnostics exceed their limit")
    if completed.returncode != 0:
        raise _BrainIsolationError("Brain runner failed")
    return _parse_runner_response(completed.stdout)


def _filename(value: Any) -> str:
    if not isinstance(value, str) or _FILENAME_RE.fullmatch(value) is None:
        raise BrainError("INVALID_SCHEMA", 400, "filename is invalid")
    try:
        _safe_relative(value, label="filename", metis_only=True)
    except _BrainIsolationError as error:
        raise BrainError("INVALID_SCHEMA", 400, "filename is invalid") from error
    return value


def validate_compile_request(
    *, source: Any, filename: Any, execution_mode: Any, endpoint: Any
) -> tuple[str, str, str, str | None]:
    source_text = bounded_source(source)
    filename_text = _filename(filename)
    if execution_mode not in {"source", "endpoint"}:
        raise BrainError("INVALID_SCHEMA", 400, "execution_mode is invalid")
    if endpoint is not None and (
        not isinstance(endpoint, str) or not endpoint or len(endpoint) > 256
    ):
        raise BrainError("INVALID_SCHEMA", 400, "endpoint is invalid")
    if execution_mode == "source" and endpoint is not None:
        raise BrainError("INVALID_SCHEMA", 400, "source mode requires a null endpoint")
    if execution_mode == "endpoint" and endpoint is None:
        raise BrainError("INVALID_SCHEMA", 400, "endpoint mode requires an endpoint")
    return source_text, filename_text, execution_mode, endpoint


class _PinnedBridge:
    def __init__(
        self,
        *,
        metis_root: Path,
        node_path: Path,
        max_concurrency: int,
    ) -> None:
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= 8:
            raise BrainError("INVALID_CONFIG", 500, "toolchain concurrency is invalid")
        try:
            self._metis_root = Path(metis_root).resolve(strict=True)
            self._node_path = Path(node_path).resolve(strict=True)
            self._pin, self._external_identity = _brain_pin_identity(
                self._metis_root,
                self._node_path,
            )
            if not sandbox_support.SANDBOX_EXEC.is_file():
                raise _BrainIsolationError("compiler sandbox is unavailable")
        except (
            brain_pin.BrainToolchainPinError,
            sandbox_support.CatalogMaintenancePinError,
            _BrainIsolationError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            raise BrainError(
                "TOOLCHAIN_UNAVAILABLE", 503, "pinned toolchain is unavailable"
            ) from error
        self._binding = toolchain_binding_from_pin(self._pin)
        self._slots = threading.BoundedSemaphore(max_concurrency)

    @property
    def pin_identity(self) -> dict[str, Any]:
        return dict(self._pin)

    @property
    def toolchain_binding(self) -> str:
        return self._binding

    @contextmanager
    def _slot(self, *, busy_code: str) -> Iterator[None]:
        if not self._slots.acquire(blocking=False):
            raise BrainError(busy_code, 429, "local toolchain capacity is exhausted")
        try:
            yield
        finally:
            self._slots.release()


class BrainCompiler(_PinnedBridge):
    """Compile caller source against the immutable session snapshot."""

    def __init__(
        self,
        *,
        metis_root: Path,
        node_path: Path,
        max_concurrency: int = 2,
    ) -> None:
        super().__init__(
            metis_root=metis_root,
            node_path=node_path,
            max_concurrency=max_concurrency,
        )
        self._execution_lock = threading.Lock()
        self._execution_count = 0

    @property
    def execution_count(self) -> int:
        with self._execution_lock:
            return self._execution_count

    def compile(
        self,
        *,
        lease: OperationLease,
        source: Any,
        filename: Any,
        execution_mode: Any,
        endpoint: Any,
    ) -> dict[str, Any]:
        source_text, filename_text, execution_mode, endpoint = validate_compile_request(
            source=source,
            filename=filename,
            execution_mode=execution_mode,
            endpoint=endpoint,
        )
        if lease.cancellation.is_set():
            raise BrainError("SESSION_REVOKED", 409, "session was revoked")
        if lease.snapshot.toolchain_binding != self._binding:
            raise BrainError("STALE_CONTEXT", 409, "session toolchain binding is stale")
        try:
            with (
                self._slot(busy_code="COMPILER_BUSY"),
                _isolated_metis_repository(
                    metis_root=self._metis_root,
                    node_path=self._node_path,
                    expected_identity=self._external_identity,
                ) as isolated_root,
            ):
                tenant_root = _materialize_snapshot(
                    lease.snapshot,
                    isolated_root,
                    candidate_filename=filename_text,
                    candidate_source=source_text,
                )
                envelope = _run_brain_runner(
                    isolated_root=isolated_root,
                    node_path=self._node_path,
                    request={
                        "schema_version": 1,
                        "operation": "compile",
                        "tenant_root": str(tenant_root),
                        "endpoint": endpoint if execution_mode == "endpoint" else None,
                    },
                )
        except BrainError:
            raise
        except (
            brain_pin.BrainToolchainPinError,
            sandbox_support.CatalogMaintenancePinError,
            _BrainIsolationError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            raise BrainError("COMPILER_FAILED", 503, "pinned compiler execution failed") from error
        if lease.cancellation.is_set():
            raise BrainError("SESSION_REVOKED", 409, "session was revoked")
        if (
            set(envelope)
            != {
                "schema_version",
                "operation",
                "status",
                "diagnostics",
                "endpoint",
                "endpoint_sha256",
                "runtime_context_sha256",
            }
            or envelope.get("schema_version") != 1
            or envelope.get("operation") != "compile"
            or envelope.get("status") not in {"ok", "invalid"}
            or not isinstance(envelope.get("diagnostics"), list)
        ):
            raise BrainError("COMPILER_FAILED", 503, "pinned compiler returned an invalid receipt")
        with self._execution_lock:
            self._execution_count += 1
        candidate = {
            "filename": filename_text,
            "execution_mode": execution_mode,
            "endpoint": endpoint,
            "source_sha256": canonical_sha256(source_text),
            "context_revision": lease.snapshot.revision,
        }
        receipt: dict[str, Any] = {
            "schema_version": 1,
            "status": envelope["status"],
            "session_id": lease.session_id,
            "tenant_alias": lease.tenant_alias,
            "context_revision": lease.snapshot.revision,
            "toolchain_binding": self._binding,
            "candidate": candidate,
            "compiler": envelope,
            "claims": {
                "archive_snapshot": True,
                "network_denied": True,
                "writes_denied": True,
                "tenant_modified": False,
                "semantic_correctness": False,
            },
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt


class PinnedCatalogProjectionLoader(_PinnedBridge):
    """Build the complete normalized schema-2 projection from one snapshot."""

    def __init__(
        self,
        *,
        metis_root: Path,
        node_path: Path,
        max_concurrency: int = 2,
    ) -> None:
        super().__init__(
            metis_root=metis_root,
            node_path=node_path,
            max_concurrency=max_concurrency,
        )

    def __call__(self, snapshot: ContextSnapshot) -> LoadedProjection:
        if snapshot.toolchain_binding != self._binding:
            raise BrainError("STALE_CONTEXT", 409, "session toolchain binding is stale")
        try:
            with (
                self._slot(busy_code="RETRIEVAL_BUSY"),
                _isolated_metis_repository(
                    metis_root=self._metis_root,
                    node_path=self._node_path,
                    expected_identity=self._external_identity,
                ) as isolated_root,
            ):
                tenant_root = _materialize_snapshot(snapshot, isolated_root)
                response = _run_brain_runner(
                    isolated_root=isolated_root,
                    node_path=self._node_path,
                    request={
                        "schema_version": 1,
                        "operation": "semantic-catalog",
                        "tenant_root": str(tenant_root),
                    },
                )
            if (
                set(response) != {"schema_version", "operation", "describe", "values", "counts"}
                or response.get("schema_version") != 1
                or response.get("operation") != "semantic-catalog"
                or not isinstance(response.get("describe"), Mapping)
                or not isinstance(response.get("values"), list)
                or not isinstance(response.get("counts"), Mapping)
            ):
                raise _BrainIsolationError("semantic runner response has an invalid shape")
            joined = build_catalog_semantic_projection(response["describe"], response["values"])
            receipt = joined["receipt"]
            if validate_catalog_projection_receipt(receipt):
                raise _BrainIsolationError("semantic projection receipt is invalid")
            counts = response["counts"]
            projected = receipt["counts"]
            if (
                counts.get("catalogs") != projected["catalogs"]
                or counts.get("finite_fields") != projected["values_responses"]
                or counts.get("values") != projected["values"]
            ):
                raise _BrainIsolationError("semantic projection counts differ from runner")
        except BrainError:
            raise
        except (
            VideoCatalogProjectionError,
            brain_pin.BrainToolchainPinError,
            sandbox_support.CatalogMaintenancePinError,
            _BrainIsolationError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            raise BrainError(
                "RETRIEVAL_UNAVAILABLE", 503, "pinned semantic retrieval failed"
            ) from error
        return LoadedProjection(
            projection=joined["projection"],
            snapshot_revision=snapshot.revision,
            semantic_source_revision=snapshot.semantic_source_revision(),
        )


__all__ = [
    "BrainCompiler",
    "PinnedCatalogProjectionLoader",
    "RUNNER_SHA256",
    "validate_compile_request",
]
