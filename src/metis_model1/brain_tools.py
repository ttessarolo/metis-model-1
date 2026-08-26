"""Session-bound Metis compiler bridge for Metis Brain."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from metis_model1 import catalog_maintenance_pin as catalog_pin
from metis_model1 import grammar_stdlib_oracle as grammar_oracle
from metis_model1.brain_context import toolchain_binding_from_pin
from metis_model1.brain_protocol import BrainError, bounded_source, canonical_sha256
from metis_model1.brain_sessions import OperationLease

_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\.metis$")


class _BrainIsolationError(RuntimeError):
    pass


def _brain_pin_identity(metis_root: Path) -> tuple[dict[str, Any], tuple[str, str, str]]:
    """Validate the immutable pin without admitting dirty worktree bytes."""

    errors = catalog_pin.validate_catalog_maintenance_pin_contract()
    if errors:
        raise _BrainIsolationError("catalog maintenance pin is invalid")
    manifest = catalog_pin.load_catalog_maintenance_pin()
    try:
        root = Path(metis_root).resolve(strict=True)
        if not root.is_dir():
            raise _BrainIsolationError("Metis Git authority is not a directory")
        revision = str(catalog_pin._run_git(root, "rev-parse", manifest["revision"]))
        tree = str(catalog_pin._run_git(root, "rev-parse", f"{manifest['revision']}^{{tree}}"))
        modules = catalog_pin._node_modules_sha256(
            (root / "tooling/node_modules").resolve(strict=True)
        )
        expected_modules = str(manifest["runtime"]["node_modules_sha256"]).removeprefix("sha256:")
        if (
            revision != manifest["revision"]
            or tree != manifest["tree"]
            or modules != expected_modules
        ):
            raise _BrainIsolationError("pinned Metis Git/runtime identity drift")
        overlay = grammar_oracle._overlay(root, manifest)
    except (catalog_pin.CatalogMaintenancePinError, OSError) as error:
        raise _BrainIsolationError("pinned Metis authority is unavailable") from error
    pin_identity = {
        "catalog_pin_id": manifest["pin_id"],
        "catalog_pin_sha256": catalog_pin.manifest_sha256(manifest),
        "revision": manifest["revision"],
        "tree": manifest["tree"],
        "language_version": grammar_oracle.LANGUAGE_VERSION,
        "overlay": overlay,
    }
    return pin_identity, (revision, tree, modules)


def _common_objects_directory(metis_root: Path) -> Path:
    raw = str(catalog_pin._run_git(metis_root, "rev-parse", "--git-common-dir"))
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = metis_root / candidate
    objects = (candidate.resolve(strict=True) / "objects").resolve(strict=True)
    if not objects.is_dir():
        raise _BrainIsolationError("Metis Git object authority is unavailable")
    return objects


def _write_git_alternate(path: Path, objects: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        raw = (str(objects) + "\n").encode("utf-8")
        if os.write(descriptor, raw) != len(raw):
            raise _BrainIsolationError("cannot bind isolated Git objects")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _isolated_metis_repository(
    *,
    metis_root: Path,
    node_path: Path,
    expected_identity: tuple[str, str, str],
) -> Iterator[Path]:
    """Materialize a clean pin while keeping the shared Metis checkout read-only."""

    manifest = catalog_pin.load_catalog_maintenance_pin()
    root = Path(metis_root).resolve(strict=True)
    before_pin, before_identity = _brain_pin_identity(root)
    if before_identity != expected_identity:
        raise _BrainIsolationError("Metis authority changed before isolation")
    del before_pin
    node_bytes = catalog_pin._verify_node(node_path, manifest["runtime"])
    archive = catalog_pin._run_git(
        root,
        "archive",
        "--format=tar",
        manifest["revision"],
        text=False,
    )
    if not isinstance(archive, bytes):
        raise _BrainIsolationError("pinned Git archive is unavailable")
    objects = _common_objects_directory(root)
    source_modules = (root / "tooling/node_modules").resolve(strict=True)
    expected_modules = expected_identity[2]

    try:
        with tempfile.TemporaryDirectory(prefix="metis-brain-authority-") as temporary:
            isolated = Path(temporary) / "metis"
            isolated.mkdir(mode=0o700)
            catalog_pin._safe_extract_archive(archive, isolated)
            before_modules = catalog_pin._node_modules_sha256(source_modules)
            if before_modules != expected_modules:
                raise _BrainIsolationError("tooling runtime changed before copy")
            snapshot_modules = isolated / "tooling/node_modules"
            shutil.copytree(source_modules, snapshot_modules, symlinks=True)
            copied_modules = catalog_pin._node_modules_sha256(snapshot_modules)
            after_modules = catalog_pin._node_modules_sha256(source_modules)
            if copied_modules != expected_modules or after_modules != expected_modules:
                raise _BrainIsolationError("copied tooling runtime differs from pin")

            catalog_pin._run_git(isolated, "init", "--quiet")
            _write_git_alternate(isolated / ".git/objects/info/alternates", objects)
            catalog_pin._run_git(
                isolated,
                "update-ref",
                "refs/heads/brain-pinned",
                manifest["revision"],
            )
            catalog_pin._run_git(
                isolated,
                "symbolic-ref",
                "HEAD",
                "refs/heads/brain-pinned",
            )
            catalog_pin._run_git(isolated, "read-tree", manifest["revision"])
            tracked = str(
                catalog_pin._run_git(
                    isolated,
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=no",
                )
            )
            if tracked:
                raise _BrainIsolationError("isolated Metis archive is not clean")
            yield isolated
    except (
        catalog_pin.CatalogMaintenancePinError,
        OSError,
        shutil.Error,
    ) as error:
        raise _BrainIsolationError("cannot construct isolated Metis authority") from error
    finally:
        try:
            if catalog_pin._verify_node(node_path, manifest["runtime"]) != node_bytes:
                raise _BrainIsolationError("Node authority changed during isolation")
            _after_pin, after_identity = _brain_pin_identity(root)
            if after_identity != expected_identity:
                raise _BrainIsolationError("Metis authority changed during isolation")
        except (catalog_pin.CatalogMaintenancePinError, OSError) as error:
            raise _BrainIsolationError("Metis authority changed during isolation") from error


def _filename(value: Any) -> str:
    if not isinstance(value, str) or _FILENAME_RE.fullmatch(value) is None:
        raise BrainError("INVALID_SCHEMA", 400, "filename is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise BrainError("INVALID_SCHEMA", 400, "filename is invalid")
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
    return source_text, filename_text, execution_mode, endpoint


class BrainCompiler:
    """Run caller source only inside the existing pinned archive sandbox."""

    def __init__(
        self,
        *,
        metis_root: Path,
        node_path: Path,
        max_concurrency: int = 2,
    ) -> None:
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= 8:
            raise BrainError("INVALID_CONFIG", 500, "compiler concurrency is invalid")
        self._metis_root = Path(metis_root)
        self._node_path = Path(node_path)
        try:
            self._pin, self._external_identity = _brain_pin_identity(self._metis_root)
            manifest = catalog_pin.load_catalog_maintenance_pin()
            catalog_pin._verify_node(self._node_path, manifest["runtime"])
            if not catalog_pin.SANDBOX_EXEC.is_file():
                raise _BrainIsolationError("pinned compiler sandbox is unavailable")
        except (
            catalog_pin.CatalogMaintenancePinError,
            grammar_oracle.GrammarStdlibOracleError,
            _BrainIsolationError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            raise BrainError(
                "TOOLCHAIN_UNAVAILABLE", 503, "pinned toolchain is unavailable"
            ) from error
        self._binding = toolchain_binding_from_pin(self._pin)
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._execution_lock = threading.Lock()
        self._execution_count = 0

    @property
    def pin_identity(self) -> dict[str, Any]:
        return dict(self._pin)

    @property
    def toolchain_binding(self) -> str:
        return self._binding

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

        workspace = lease.snapshot.source_map()
        workspace.pop(filename_text, None)
        if len(workspace) > grammar_oracle.MAX_WORKSPACE_SOURCES:
            raise BrainError(
                "CONTEXT_TOO_LARGE",
                422,
                "context exceeds the pinned compiler workspace source limit",
            )
        for workspace_source in workspace.values():
            source_bytes = workspace_source.encode("utf-8")
            if not workspace_source or len(source_bytes) > grammar_oracle.MAX_SOURCE_BYTES:
                raise BrainError(
                    "CONTEXT_UNSUPPORTED",
                    422,
                    "context contains a source outside the pinned compiler limits",
                )
        if not self._slots.acquire(blocking=False):
            raise BrainError("COMPILER_BUSY", 429, "compiler capacity is exhausted")
        try:
            with (
                _isolated_metis_repository(
                    metis_root=self._metis_root,
                    node_path=self._node_path,
                    expected_identity=self._external_identity,
                ) as isolated_root,
                grammar_oracle.grammar_stdlib_oracle_session(
                    metis_root=isolated_root,
                    node_path=self._node_path,
                ) as session,
            ):
                envelope = session.run(
                    source=source_text,
                    filename=filename_text,
                    execution_mode=execution_mode,
                    endpoint=endpoint,
                    workspace_sources=workspace,
                )
        except (
            catalog_pin.CatalogMaintenancePinError,
            grammar_oracle.GrammarStdlibOracleError,
            _BrainIsolationError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            raise BrainError("COMPILER_FAILED", 503, "pinned compiler execution failed") from error
        finally:
            self._slots.release()
        if lease.cancellation.is_set():
            raise BrainError("SESSION_REVOKED", 409, "session was revoked")
        with self._execution_lock:
            self._execution_count += 1

        candidate = {
            "filename": filename_text,
            "execution_mode": execution_mode,
            "endpoint": endpoint,
            "source_sha256": canonical_sha256(source_text),
            "context_revision": lease.snapshot.revision,
        }
        receipt = {
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
