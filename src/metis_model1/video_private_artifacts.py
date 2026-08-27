"""Fail-closed boundary for the private video-semantics artifact root.

This module deliberately handles no source or artifact payload. It verifies
only the fixed local root, an ephemeral synthetic sentinel, and Git metadata;
the public receipt contains booleans and no filesystem or source identity.
"""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any


class VideoArtifactBoundaryError(RuntimeError):
    """Raised when the fixed private artifact boundary cannot be proven."""


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT_RELATIVE = Path("artifacts/video-catalog-semantics-v1")
SENTINEL_NAME = ".boundary-sentinel"
SENTINEL_BYTES = b"METIS_VIDEO_ARTIFACT_BOUNDARY_SENTINEL_V1\n"
_SYNC_MARKERS = (
    "/library/cloudstorage/",
    "/library/mobile documents/",
    "/dropbox/",
    "/google drive/",
    "/onedrive/",
)
_STATUS_ARGS = ("status", "--porcelain=v1", "--untracked-files=all")
_SYSTEM_GIT_PATH = Path("/usr/bin/git")
GitRunner = Callable[[Path, tuple[str, ...]], subprocess.CompletedProcess[bytes]]


def _fail() -> None:
    raise VideoArtifactBoundaryError("video artifact boundary is not safe")


def _current_uid() -> int:
    getuid = getattr(os, "getuid", None)
    if not callable(getuid):
        _fail()
    return int(getuid())


def _assert_directory(path: Path, *, expected_mode: int | None = None) -> os.stat_result:
    """Check a directory using lstat, no-follow open, owner and mode."""

    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
            _fail()
        if before.st_uid != _current_uid():
            _fail()
        if expected_mode is not None and stat.S_IMODE(before.st_mode) != expected_mode:
            _fail()
        nofollow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if nofollow is None or directory is None:
            _fail()
        descriptor = os.open(path, os.O_RDONLY | directory | nofollow)
        try:
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except (OSError, VideoArtifactBoundaryError):
        raise VideoArtifactBoundaryError("video artifact boundary is not safe") from None
    if (
        (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        or stat.S_ISLNK(after.st_mode)
        or not stat.S_ISDIR(after.st_mode)
        or after.st_uid != _current_uid()
        or (expected_mode is not None and stat.S_IMODE(after.st_mode) != expected_mode)
    ):
        _fail()
    return after


def _repository_root() -> Path:
    try:
        root = PROJECT_ROOT.resolve(strict=True)
        root.relative_to(root.anchor)
    except (OSError, ValueError):
        _fail()
    _assert_directory(root)
    _assert_known_cloud_sync_path_absent(root)
    return root


def _assert_known_cloud_sync_path_absent(root: Path) -> None:
    """Reject only the repository locations covered by our marker allowlist.

    This is intentionally a bounded check. It does not inspect sync daemons,
    provider databases, or any other universal cloud-sync state.
    """

    lowered = (os.fspath(root) + "/").lower()
    if any(marker in lowered for marker in _SYNC_MARKERS):
        _fail()


def _mkdir_direct_child(parent: Path, name: str, mode: int) -> None:
    """Create one fixed child through an anchored no-follow directory FD."""

    descriptor = _open_directory_fd(parent)
    try:
        os.mkdir(name, mode=mode, dir_fd=descriptor)
        os.fsync(descriptor)
    except (OSError, VideoArtifactBoundaryError):
        raise VideoArtifactBoundaryError("video artifact boundary is not safe") from None
    finally:
        os.close(descriptor)


def _open_directory_fd(path: Path) -> int:
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if nofollow is None or directory is None:
            _fail()
        descriptor = os.open(path, os.O_RDONLY | directory | nofollow)
        checked = path.lstat()
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(checked.st_mode)
            or not stat.S_ISDIR(checked.st_mode)
            or (checked.st_dev, checked.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            os.close(descriptor)
            _fail()
        return descriptor
    except (OSError, VideoArtifactBoundaryError):
        raise VideoArtifactBoundaryError("video artifact boundary is not safe") from None


def _artifact_root(root: Path) -> Path:
    candidate = root / ARTIFACT_ROOT_RELATIVE
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        _fail()
    _assert_directory(root)
    artifacts = root / "artifacts"
    if artifacts.exists() or artifacts.is_symlink():
        _assert_directory(artifacts)
    else:
        try:
            _mkdir_direct_child(root, "artifacts", 0o700)
            _assert_directory(artifacts, expected_mode=0o700)
        except (OSError, VideoArtifactBoundaryError):
            raise VideoArtifactBoundaryError("video artifact boundary is not safe") from None
    return candidate


def _ensure_private_root(root: Path) -> tuple[Path, bool]:
    target = _artifact_root(root)
    if target.exists() or target.is_symlink():
        _assert_directory(target, expected_mode=0o700)
        return target, False
    try:
        _mkdir_direct_child(target.parent, target.name, 0o700)
        _assert_directory(target, expected_mode=0o700)
    except (OSError, VideoArtifactBoundaryError):
        raise VideoArtifactBoundaryError("video artifact boundary is not safe") from None
    return target, True


def _git_identity(path: Path) -> tuple[int, int, int, int, int, int, int]:
    info = path.lstat()
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _verify_system_git() -> tuple[Path, tuple[int, int, int, int, int, int, int]]:
    """Require the Git authority to be a fixed, system-owned executable.

    Git is deliberately not resolved through ``PATH``.  Every directory in
    the executable's ancestry is checked as well, so an attacker cannot
    substitute a user-owned or writable parent while the probe is prepared.
    """

    try:
        executable = Path(_SYSTEM_GIT_PATH)
        if not executable.is_absolute():
            _fail()
        chain = (executable, *executable.parents)
        for index, path in enumerate(chain):
            info = path.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or info.st_uid != 0
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            ):
                _fail()
            if index == 0 and (not stat.S_ISREG(info.st_mode) or not info.st_mode & stat.S_IXUSR):
                _fail()
        identity = _git_identity(executable)
    except (OSError, VideoArtifactBoundaryError):
        raise VideoArtifactBoundaryError("video artifact boundary is not safe") from None
    return executable, identity


def _default_git(root: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[bytes]:
    executable, identity = _verify_system_git()
    # The probe gets a bounded environment.  In particular, no inherited
    # GIT_DIR/GIT_INDEX_FILE or helper/config variables can redirect it away
    # from the repository passed as cwd.
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    command = [
        str(executable),
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "-c",
        "core.excludesFile=/dev/null",
        *args,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
            env=environment,
        )
        if _git_identity(executable) != identity:
            _fail()
        return result
    except (OSError, subprocess.SubprocessError, VideoArtifactBoundaryError):
        _fail()


def _git_status(root: Path, git: GitRunner) -> bytes:
    result = git(root, _STATUS_ARGS)
    if result.returncode != 0 or not isinstance(result.stdout, bytes):
        _fail()
    return result.stdout


def _git_ignored(root: Path, git: GitRunner, relative: str) -> bool:
    result = git(root, ("check-ignore", "--quiet", "--no-index", "--", relative))
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    _fail()


def _git_tracked_under_root(root: Path, git: GitRunner) -> bool:
    """Return whether Git tracks any path below the private root.

    Git output is inspected only in memory and never copied into a receipt or
    diagnostic. This keeps tracked names and object metadata out of the public
    boundary contract.
    """

    relative_root = ARTIFACT_ROOT_RELATIVE.as_posix().rstrip("/") + "/"
    result = git(root, ("ls-files", "-z", "--", relative_root))
    if result.returncode != 0 or not isinstance(result.stdout, bytes):
        _fail()
    return bool(result.stdout)


def _open_root_fd(root: Path) -> int:
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if nofollow is None or directory is None:
            _fail()
        descriptor = os.open(root, os.O_RDONLY | directory | nofollow)
        opened = os.fstat(descriptor)
        checked = root.lstat()
        if (
            stat.S_ISLNK(checked.st_mode)
            or not stat.S_ISDIR(checked.st_mode)
            or (opened.st_dev, opened.st_ino) != (checked.st_dev, checked.st_ino)
            or opened.st_uid != _current_uid()
            or stat.S_IMODE(opened.st_mode) != 0o700
        ):
            os.close(descriptor)
            _fail()
        return descriptor
    except (OSError, VideoArtifactBoundaryError):
        raise VideoArtifactBoundaryError("video artifact boundary is not safe") from None


def _create_and_remove_sentinel(root: Path) -> None:
    descriptor = _open_root_fd(root)
    child: int | None = None
    created = False
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        close_on_exec = getattr(os, "O_CLOEXEC", 0)
        if nofollow is None:
            _fail()
        child = os.open(
            SENTINEL_NAME,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow | close_on_exec,
            0o600,
            dir_fd=descriptor,
        )
        created = True
        view = memoryview(SENTINEL_BYTES)
        while view:
            written = os.write(child, view)
            if written <= 0:
                _fail()
            view = view[written:]
        os.fsync(child)
        os.fsync(descriptor)
        fd_info = os.fstat(child)
        info = os.stat(SENTINEL_NAME, dir_fd=descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != _current_uid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or info.st_size != len(SENTINEL_BYTES)
            or (fd_info.st_dev, fd_info.st_ino) != (info.st_dev, info.st_ino)
        ):
            _fail()
        os.unlink(SENTINEL_NAME, dir_fd=descriptor)
        created = False
        os.fsync(descriptor)
        if os.fstat(child).st_nlink != 0:
            _fail()
        os.close(child)
        child = None
    except (OSError, VideoArtifactBoundaryError):
        raise VideoArtifactBoundaryError("video artifact boundary is not safe") from None
    finally:
        if child is not None:
            with suppress(OSError):
                os.close(child)
        if created:
            try:
                os.unlink(SENTINEL_NAME, dir_fd=descriptor)
                os.fsync(descriptor)
            except OSError:
                pass
        os.close(descriptor)


def _prepare_artifact_boundary(root: Path, git: GitRunner) -> dict[str, Any]:
    """Testable implementation; callers must provide the fixed root and Git probe."""

    root = root.resolve(strict=True)
    _assert_directory(root)
    _assert_known_cloud_sync_path_absent(root)
    before = _git_status(root, git)
    try:
        private_root, _ = _ensure_private_root(root)
        if _git_tracked_under_root(root, git) or not _git_ignored(
            root, git, ARTIFACT_ROOT_RELATIVE.as_posix() + "/"
        ):
            _fail()
        _create_and_remove_sentinel(private_root)
        if (
            private_root.joinpath(SENTINEL_NAME).exists()
            or private_root.joinpath(SENTINEL_NAME).is_symlink()
        ):
            _fail()
        if _git_tracked_under_root(root, git) or not _git_ignored(
            root, git, ARTIFACT_ROOT_RELATIVE.as_posix() + "/"
        ):
            _fail()
        after = _git_status(root, git)
        if before != after:
            _fail()
    except VideoArtifactBoundaryError:
        raise
    except (OSError, ValueError):
        raise VideoArtifactBoundaryError("video artifact boundary is not safe") from None
    return {
        "schema_version": 1,
        "contract_id": "video-private-artifact-boundary-v1",
        "status": "VALID",
        "root_contained": True,
        "root_not_symlink": True,
        "root_mode_0700": True,
        "file_mode_0600": True,
        "symlinks_rejected": True,
        "known_cloud_sync_path_absent": True,
        "universal_cloud_sync_scan_not_performed": True,
        "sentinel_ignored": True,
        "sentinel_removed": True,
        "git_status_unchanged": True,
        "tracked_collision": False,
        "sensitive_material_accessed": False,
    }


def prepare_artifact_boundary() -> dict[str, Any]:
    """Prove the fixed private root and return a path-free public receipt."""

    return _prepare_artifact_boundary(_repository_root(), _default_git)


def validate_public_receipt(receipt: Mapping[str, Any]) -> None:
    """Validate the deliberately small, path-free public receipt."""

    expected = {
        "schema_version",
        "contract_id",
        "status",
        "root_contained",
        "root_not_symlink",
        "root_mode_0700",
        "file_mode_0600",
        "symlinks_rejected",
        "known_cloud_sync_path_absent",
        "universal_cloud_sync_scan_not_performed",
        "sentinel_ignored",
        "sentinel_removed",
        "git_status_unchanged",
        "tracked_collision",
        "sensitive_material_accessed",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != expected:
        raise VideoArtifactBoundaryError("public artifact receipt is invalid")
    if (
        type(receipt["schema_version"]) is not int
        or receipt["schema_version"] != 1
        or receipt["contract_id"] != "video-private-artifact-boundary-v1"
        or receipt["status"] != "VALID"
        or any(
            receipt[key] is not True
            for key in (
                "root_contained",
                "root_not_symlink",
                "root_mode_0700",
                "file_mode_0600",
                "symlinks_rejected",
                "known_cloud_sync_path_absent",
                "universal_cloud_sync_scan_not_performed",
                "sentinel_ignored",
                "sentinel_removed",
                "git_status_unchanged",
            )
        )
        or receipt["tracked_collision"] is not False
        or receipt["sensitive_material_accessed"] is not False
    ):
        raise VideoArtifactBoundaryError("public artifact receipt is invalid")
