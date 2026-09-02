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
from dataclasses import dataclass
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
RUNNER_SHA256 = "sha256:b793c47d71c9e24dad49acd1e5002e2c8899bc37de53fdf65f7b75a174ad3e9c"
MAX_RUNNER_BYTES = 256 * 1024
MAX_RUNNER_REQUEST_BYTES = 256 * 1024
MAX_RUNNER_STDOUT_BYTES = 32 * 1024 * 1024
MAX_RUNNER_STDERR_BYTES = 128 * 1024
MAX_SNAPSHOT_FILES = 1024
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
RUNNER_TIMEOUT_SECONDS = 180


class _BrainIsolationError(RuntimeError):
    pass


_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


@dataclass(frozen=True)
class _AuthorityJob:
    authority_root: Path
    job_root: Path


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


def _seal_tree_readonly(root: Path) -> None:
    """Remove write bits once from the private authority without following links."""

    for current, directories, filenames in os.walk(root, topdown=False, followlinks=False):
        base = Path(current)
        for name in (*filenames, *directories):
            target = base / name
            status = target.lstat()
            if stat.S_ISLNK(status.st_mode):
                continue
            if not (stat.S_ISREG(status.st_mode) or stat.S_ISDIR(status.st_mode)):
                raise _BrainIsolationError("Metis authority contains an unsupported node")
            os.chmod(target, stat.S_IMODE(status.st_mode) & ~_WRITE_BITS, follow_symlinks=False)
    status = root.lstat()
    os.chmod(root, stat.S_IMODE(status.st_mode) & ~_WRITE_BITS, follow_symlinks=False)


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


class PinnedMetisAuthority:
    """One verified, process-private Metis capsule shared by all Brain tools."""

    def __init__(self, *, metis_root: Path, node_path: Path) -> None:
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
        self._lock = threading.RLock()
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._authority_root: Path | None = None
        self._jobs_root: Path | None = None
        self._runner: bytes | None = None
        self._node_bytes: bytes | None = None
        self._authority_identity: tuple[int, ...] | None = None
        self._modules_identity: tuple[int, ...] | None = None
        self._active_jobs = 0
        self._closed = False

    @property
    def metis_root(self) -> Path:
        return self._metis_root

    @property
    def node_path(self) -> Path:
        return self._node_path

    @property
    def pin_identity(self) -> dict[str, Any]:
        return dict(self._pin)

    @property
    def external_identity(self) -> tuple[str, str, str]:
        return self._external_identity

    @property
    def toolchain_binding(self) -> str:
        return self._binding

    def _build_locked(self) -> None:
        if self._authority_root is not None:
            return
        if self._closed:
            raise _BrainIsolationError("Metis authority is closed")
        manifest = brain_pin.load_metis_brain_toolchain_pin()
        runner = _runner_bytes()
        node_bytes = brain_pin._verify_node(self._node_path, manifest["runtime"])
        archive = brain_pin._git(
            self._metis_root,
            "archive",
            "--format=tar",
            manifest["revision"],
            text=False,
        )
        if not isinstance(archive, bytes):
            raise _BrainIsolationError("pinned Git archive is unavailable")
        source_modules = (self._metis_root / "tooling/node_modules").resolve(strict=True)
        if brain_pin._node_modules_sha256(source_modules) != self._external_identity[2]:
            raise _BrainIsolationError("tooling runtime changed before capsule creation")

        temporary: tempfile.TemporaryDirectory[str] | None = None
        try:
            temporary = tempfile.TemporaryDirectory(prefix="metis-brain-authority-")
            sandbox_root = Path(temporary.name)
            authority_root = sandbox_root / "authority"
            jobs_root = sandbox_root / "jobs"
            authority_root.mkdir(mode=0o700)
            jobs_root.mkdir(mode=0o700)
            sandbox_support._safe_extract_archive(archive, authority_root)
            capsule_modules = authority_root / "tooling/node_modules"
            shutil.copytree(source_modules, capsule_modules, symlinks=True)
            if (
                brain_pin._node_modules_sha256(capsule_modules) != self._external_identity[2]
                or brain_pin._node_modules_sha256(source_modules) != self._external_identity[2]
            ):
                raise _BrainIsolationError("copied tooling runtime differs from pin")
            runner_target = authority_root / "runtime/metis_brain/runner.mts"
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
            if brain_pin._verify_node(self._node_path, manifest["runtime"]) != node_bytes:
                raise _BrainIsolationError("Node authority changed during capsule creation")
            if _runner_bytes() != runner:
                raise _BrainIsolationError("Brain runner changed during capsule creation")
            _seal_tree_readonly(authority_root)
            self._temporary = temporary
            self._authority_root = authority_root
            self._jobs_root = jobs_root
            self._runner = runner
            self._node_bytes = node_bytes
            self._authority_identity = _stat_identity(authority_root.lstat())
            self._modules_identity = _stat_identity(capsule_modules.lstat())
        except (
            brain_pin.BrainToolchainPinError,
            sandbox_support.CatalogMaintenancePinError,
            _BrainIsolationError,
            OSError,
            shutil.Error,
        ) as error:
            if temporary is not None:
                temporary.cleanup()
            if isinstance(error, _BrainIsolationError):
                raise
            raise _BrainIsolationError("cannot construct isolated Metis authority") from error

    def _check_capsule_locked(self) -> None:
        assert self._authority_root is not None
        assert self._runner is not None
        assert self._node_bytes is not None
        assert self._authority_identity is not None
        assert self._modules_identity is not None
        manifest = brain_pin.load_metis_brain_toolchain_pin()
        runner_target = self._authority_root / "runtime/metis_brain/runner.mts"
        modules = self._authority_root / "tooling/node_modules"
        if (
            _stat_identity(self._authority_root.lstat()) != self._authority_identity
            or _stat_identity(modules.lstat()) != self._modules_identity
            or self._authority_root.lstat().st_mode & _WRITE_BITS
            or modules.lstat().st_mode & _WRITE_BITS
            or _stable_regular_bytes(
                runner_target,
                label="isolated Brain runner",
                maximum=MAX_RUNNER_BYTES,
            )
            != self._runner
            or brain_pin._verify_node(self._node_path, manifest["runtime"]) != self._node_bytes
        ):
            raise _BrainIsolationError("process-private Metis authority changed")

    @contextmanager
    def job(self) -> Iterator[_AuthorityJob]:
        with self._lock:
            self._build_locked()
            self._check_capsule_locked()
            if self._closed:
                raise _BrainIsolationError("Metis authority is closed")
            assert self._authority_root is not None
            assert self._jobs_root is not None
            self._active_jobs += 1
            authority_root = self._authority_root
            jobs_root = self._jobs_root
        try:
            with tempfile.TemporaryDirectory(prefix="job-", dir=jobs_root) as temporary:
                yield _AuthorityJob(authority_root, Path(temporary))
        finally:
            with self._lock:
                self._active_jobs -= 1
                self._check_capsule_locked()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._active_jobs:
                raise BrainError("TOOLCHAIN_BUSY", 503, "pinned toolchain is still active")
            self._closed = True
            temporary = self._temporary
            self._temporary = None
            self._authority_root = None
            self._jobs_root = None
        if temporary is not None:
            temporary.cleanup()


@contextmanager
def _isolated_metis_repository(
    *,
    metis_root: Path,
    node_path: Path,
    expected_identity: tuple[str, str, str],
    authority: PinnedMetisAuthority | None = None,
) -> Iterator[_AuthorityJob]:
    """Open one bounded job over a verified reusable authority capsule."""

    owned = authority is None
    capsule = authority or PinnedMetisAuthority(metis_root=metis_root, node_path=node_path)
    if (
        capsule.metis_root != Path(metis_root).resolve(strict=True)
        or capsule.node_path != Path(node_path).resolve(strict=True)
        or capsule.external_identity != expected_identity
    ):
        if owned:
            capsule.close()
        raise _BrainIsolationError("Metis authority identity differs")
    try:
        with capsule.job() as job:
            yield job
    finally:
        if owned:
            capsule.close()


def _job_paths(value: _AuthorityJob | Path) -> tuple[Path, Path, tuple[Path, ...]]:
    """Accept the legacy Path shape used by bounded test doubles."""

    if isinstance(value, _AuthorityJob):
        return value.authority_root, value.job_root, (value.job_root,)
    return value, value, ()


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


def _sandbox_policy(
    isolated_root: Path,
    node_path: Path,
    additional_read_roots: tuple[Path, ...] = (),
) -> str:
    roots = (isolated_root, *additional_read_roots)
    if (
        not node_path.is_absolute()
        or not roots
        or any(not root.is_absolute() for root in roots)
        or len(set(roots)) != len(roots)
    ):
        raise _BrainIsolationError("sandbox paths must be absolute")
    home = Path.home().resolve(strict=True)
    return " ".join(
        (
            "(version 1)",
            "(allow default)",
            "(deny file-write*)",
            "(deny network*)",
            f"(deny file-read* (subpath {json.dumps(str(home))}))",
            *(f"(allow file-read* (subpath {json.dumps(str(root))}))" for root in roots),
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
    additional_read_roots: tuple[Path, ...] = (),
    node_path: Path,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    request_raw = canonical_json(dict(request))
    if not request_raw or len(request_raw) > MAX_RUNNER_REQUEST_BYTES:
        raise _BrainIsolationError("Brain runner request exceeds its limit")
    policy = _sandbox_policy(isolated_root, node_path, additional_read_roots)
    boundary_root = additional_read_roots[-1] if additional_read_roots else isolated_root
    sandbox_support._assert_sandbox_boundaries(boundary_root, policy)
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
            input=request_raw,
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
        authority: PinnedMetisAuthority | None = None,
    ) -> None:
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= 8:
            raise BrainError("INVALID_CONFIG", 500, "toolchain concurrency is invalid")
        self._owns_authority = authority is None
        self._authority = authority or PinnedMetisAuthority(
            metis_root=metis_root,
            node_path=node_path,
        )
        self._metis_root = self._authority.metis_root
        self._node_path = self._authority.node_path
        if self._metis_root != Path(metis_root).resolve(strict=True) or self._node_path != Path(
            node_path
        ).resolve(strict=True):
            raise BrainError("INVALID_CONFIG", 500, "shared toolchain authority differs")
        self._pin = self._authority.pin_identity
        self._external_identity = self._authority.external_identity
        self._binding = self._authority.toolchain_binding
        self._slots = threading.BoundedSemaphore(max_concurrency)

    @property
    def pin_identity(self) -> dict[str, Any]:
        return dict(self._pin)

    @property
    def toolchain_binding(self) -> str:
        return self._binding

    @property
    def authority(self) -> PinnedMetisAuthority:
        return self._authority

    def close(self) -> None:
        if self._owns_authority:
            self._authority.close()

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
        authority: PinnedMetisAuthority | None = None,
    ) -> None:
        super().__init__(
            metis_root=metis_root,
            node_path=node_path,
            max_concurrency=max_concurrency,
            authority=authority,
        )
        self._execution_lock = threading.Lock()
        self._execution_count = 0

    @property
    def execution_count(self) -> int:
        with self._execution_lock:
            return self._execution_count

    @property
    def lossless_toolchain_identity(self) -> dict[str, str]:
        """Exact compiler identity expected in every lossless receipt."""

        keys = {
            "toolingVersion": "tooling_version",
            "langiumVersion": "langium_version",
            "metisLanguageVersion": "metis_language_version",
            "grammarSha256": "grammar_sha256",
        }
        try:
            identity = {public: self._pin[pinned] for public, pinned in keys.items()}
        except KeyError as error:
            raise BrainError(
                "TOOLCHAIN_UNAVAILABLE",
                503,
                "pinned lossless toolchain identity is incomplete",
            ) from error
        if any(not isinstance(value, str) or not value for value in identity.values()):
            raise BrainError(
                "TOOLCHAIN_UNAVAILABLE",
                503,
                "pinned lossless toolchain identity is invalid",
            )
        return identity

    def _lossless_call(
        self,
        *,
        operation: str,
        lease: OperationLease,
        source: Any,
        filename: Any,
        endpoint: Any,
        plan: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_text, filename_text, _execution_mode, endpoint_text = validate_compile_request(
            source=source,
            filename=filename,
            execution_mode="endpoint",
            endpoint=endpoint,
        )
        if operation not in {"lossless-inventory", "lossless-apply"}:
            raise BrainError("INVALID_SCHEMA", 500, "lossless operation is invalid")
        if operation == "lossless-inventory" and plan is not None:
            raise BrainError("INVALID_SCHEMA", 500, "inventory request contains a plan")
        if operation == "lossless-apply" and not isinstance(plan, Mapping):
            raise BrainError("INVALID_SCHEMA", 500, "lossless plan is invalid")
        if lease.cancellation.is_set():
            raise BrainError("SESSION_REVOKED", 409, "session was revoked")
        if lease.snapshot.toolchain_binding != self._binding:
            raise BrainError("STALE_CONTEXT", 409, "session toolchain binding is stale")
        if filename_text not in {item.path for item in lease.snapshot.files}:
            raise BrainError("STALE_CONTEXT", 409, "lossless target is absent from the snapshot")
        try:
            with (
                self._slot(busy_code="COMPILER_BUSY"),
                _isolated_metis_repository(
                    metis_root=self._metis_root,
                    node_path=self._node_path,
                    expected_identity=self._external_identity,
                    authority=self._authority,
                ) as isolation,
            ):
                authority_root, job_root, additional_read_roots = _job_paths(isolation)
                tenant_root = _materialize_snapshot(
                    lease.snapshot,
                    job_root,
                    candidate_filename=filename_text,
                    candidate_source=source_text,
                )
                request: dict[str, Any] = {
                    "schema_version": 1,
                    "operation": operation,
                    "tenant_root": str(tenant_root),
                    "relative_path": filename_text,
                    "endpoint": endpoint_text,
                }
                if plan is not None:
                    request["plan"] = dict(plan)
                envelope = _run_brain_runner(
                    isolated_root=authority_root,
                    additional_read_roots=additional_read_roots,
                    node_path=self._node_path,
                    request=request,
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
            raise BrainError(
                "LOSSLESS_FAILED",
                503,
                "pinned lossless compiler execution failed",
            ) from error
        if lease.cancellation.is_set():
            raise BrainError("SESSION_REVOKED", 409, "session was revoked")
        return envelope

    def lossless_inventory(
        self,
        *,
        lease: OperationLease,
        source: Any,
        filename: Any,
        endpoint: Any,
    ) -> dict[str, Any]:
        return self._lossless_call(
            operation="lossless-inventory",
            lease=lease,
            source=source,
            filename=filename,
            endpoint=endpoint,
        )

    def lossless_apply(
        self,
        *,
        lease: OperationLease,
        source: Any,
        filename: Any,
        endpoint: Any,
        plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._lossless_call(
            operation="lossless-apply",
            lease=lease,
            source=source,
            filename=filename,
            endpoint=endpoint,
            plan=plan,
        )

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
                    authority=self._authority,
                ) as isolation,
            ):
                authority_root, job_root, additional_read_roots = _job_paths(isolation)
                tenant_root = _materialize_snapshot(
                    lease.snapshot,
                    job_root,
                    candidate_filename=filename_text,
                    candidate_source=source_text,
                )
                envelope = _run_brain_runner(
                    isolated_root=authority_root,
                    additional_read_roots=additional_read_roots,
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
        authority: PinnedMetisAuthority | None = None,
    ) -> None:
        super().__init__(
            metis_root=metis_root,
            node_path=node_path,
            max_concurrency=max_concurrency,
            authority=authority,
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
                    authority=self._authority,
                ) as isolation,
            ):
                authority_root, job_root, additional_read_roots = _job_paths(isolation)
                tenant_root = _materialize_snapshot(snapshot, job_root)
                response = _run_brain_runner(
                    isolated_root=authority_root,
                    additional_read_roots=additional_read_roots,
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
    "PinnedMetisAuthority",
    "PinnedCatalogProjectionLoader",
    "RUNNER_SHA256",
    "validate_compile_request",
]
