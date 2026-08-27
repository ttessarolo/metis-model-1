"""Fail-closed I/O for the local private video-semantics artifact store.

Only the fixed, ignored artifact root is addressable.  This module never
prints or returns paths and never performs network, credential, model, or
tenant operations.  The write primitive publishes a fully fsynced temporary
file with an atomic hard-link claim, which gives no-overwrite semantics on
platforms where ``renameat2(RENAME_NOREPLACE)`` is unavailable.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from metis_model1.video_private_artifacts import (
    ARTIFACT_ROOT_RELATIVE,
    PROJECT_ROOT,
    VideoArtifactBoundaryError,
    _default_git,
    _git_ignored,
    _git_status,
    _git_tracked_under_root,
    prepare_artifact_boundary,
    validate_public_receipt,
)

MAX_PRIVATE_FILE_BYTES = 16 * 1024 * 1024
_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600
_CHUNK_SIZE = 64 * 1024
_TEMP_ATTEMPTS = 32


class VideoPrivateIOError(RuntimeError):
    """Raised when private artifact I/O cannot be proven safe."""


@dataclass(frozen=True)
class _DirectoryChain:
    """Held directory capabilities plus their names below the fixed root."""

    descriptors: tuple[int, ...]
    names: tuple[str, ...]
    target_name: str

    @property
    def parent(self) -> int:
        return self.descriptors[-1]


def _blocked() -> None:
    raise VideoPrivateIOError("private video artifact operation blocked")


def _current_uid() -> int:
    getuid = getattr(os, "getuid", None)
    if not callable(getuid):
        _blocked()
    return int(getuid())


def _safe_relative_parts(relative_path: str | os.PathLike[str]) -> tuple[str, ...]:
    try:
        value = os.fspath(relative_path)
    except (TypeError, ValueError):
        _blocked()
    if not isinstance(value, str) or not value or "\x00" in value:
        _blocked()
    if os.path.isabs(value) or "\\" in value:
        _blocked()
    parts = tuple(value.split("/"))
    if not parts or any(not part or part in {".", ".."} for part in parts):
        _blocked()
    return parts


def _assert_owned_directory(descriptor: int, *, expected_mode: int = _DIRECTORY_MODE) -> None:
    try:
        info = os.fstat(descriptor)
    except OSError:
        _blocked()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != _current_uid()
        or stat.S_IMODE(info.st_mode) != expected_mode
    ):
        _blocked()


def _open_private_root() -> int:
    try:
        receipt = prepare_artifact_boundary()
        validate_public_receipt(receipt)
        root = PROJECT_ROOT / ARTIFACT_ROOT_RELATIVE
        nofollow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        close_on_exec = getattr(os, "O_CLOEXEC", 0)
        if nofollow is None or directory is None:
            _blocked()
        descriptor = os.open(
            root,
            os.O_RDONLY | directory | nofollow | close_on_exec,
        )
        try:
            _assert_owned_directory(descriptor)
            checked = root.lstat()
            opened = os.fstat(descriptor)
            if stat.S_ISLNK(checked.st_mode) or (
                checked.st_dev,
                checked.st_ino,
            ) != (opened.st_dev, opened.st_ino):
                _blocked()
        except Exception:
            os.close(descriptor)
            raise
        return descriptor
    except VideoPrivateIOError:
        raise
    except (OSError, ValueError, VideoArtifactBoundaryError):
        _blocked()


def _open_child_directory(parent: int, name: str, *, create: bool) -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    if nofollow is None or directory is None:
        _blocked()
    if create:
        try:
            os.mkdir(name, mode=_DIRECTORY_MODE, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
        except OSError:
            _blocked()
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | directory | nofollow | close_on_exec,
            dir_fd=parent,
        )
        _assert_owned_directory(descriptor)
        checked = os.stat(name, dir_fd=parent, follow_symlinks=False)
        opened = os.fstat(descriptor)
        if stat.S_ISLNK(checked.st_mode) or (
            checked.st_dev,
            checked.st_ino,
        ) != (opened.st_dev, opened.st_ino):
            os.close(descriptor)
            _blocked()
        return descriptor
    except VideoPrivateIOError:
        raise
    except OSError:
        _blocked()


def _open_parent(parts: tuple[str, ...], *, create: bool) -> _DirectoryChain:
    descriptors = [_open_private_root()]
    try:
        for name in parts[:-1]:
            descriptors.append(_open_child_directory(descriptors[-1], name, create=create))
        chain = _DirectoryChain(tuple(descriptors), parts[:-1], parts[-1])
        _revalidate_chain(chain)
        return chain
    except BaseException:
        for descriptor in reversed(descriptors):
            _close(descriptor)
        raise


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_file_state(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_mode,
        left.st_dev,
        left.st_ino,
        left.st_nlink,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_mode,
        right.st_dev,
        right.st_ino,
        right.st_nlink,
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


def _revalidate_chain(chain: _DirectoryChain) -> None:
    """Prove every held directory is still reachable below the fixed root."""

    for descriptor in chain.descriptors:
        _assert_owned_directory(descriptor)
    reopened: list[int] = []
    try:
        reopened.append(_open_private_root())
        if not _same_inode(os.fstat(reopened[0]), os.fstat(chain.descriptors[0])):
            _blocked()
        for index, name in enumerate(chain.names, start=1):
            reopened.append(_open_child_directory(reopened[-1], name, create=False))
            if not _same_inode(os.fstat(reopened[-1]), os.fstat(chain.descriptors[index])):
                _blocked()
    except VideoPrivateIOError:
        raise
    except OSError:
        _blocked()
    finally:
        for descriptor in reversed(reopened):
            _close(descriptor)


def _close_chain(chain: _DirectoryChain | None) -> None:
    if chain is not None:
        for descriptor in reversed(chain.descriptors):
            _close(descriptor)


def _validate_max_bytes(max_bytes: int) -> None:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
        _blocked()
    if max_bytes < 0 or max_bytes > MAX_PRIVATE_FILE_BYTES:
        _blocked()


def _assert_regular_file(
    info: os.stat_result,
    *,
    max_bytes: int | None = None,
    expected_nlink: int = 1,
) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != _current_uid()
        or stat.S_IMODE(info.st_mode) != _FILE_MODE
        or info.st_nlink != expected_nlink
        or (max_bytes is not None and info.st_size > max_bytes)
    ):
        _blocked()


def _assert_entry_matches_fd(
    entry: os.stat_result,
    descriptor: os.stat_result,
    *,
    max_bytes: int | None = None,
) -> None:
    _assert_regular_file(entry, max_bytes=max_bytes)
    _assert_regular_file(descriptor, max_bytes=max_bytes)
    if (
        (entry.st_dev, entry.st_ino) != (descriptor.st_dev, descriptor.st_ino)
        or entry.st_size != descriptor.st_size
        or entry.st_mtime_ns != descriptor.st_mtime_ns
        or entry.st_ctime_ns != descriptor.st_ctime_ns
    ):
        _blocked()


def _read_fd(descriptor: int, max_bytes: int) -> bytes:
    try:
        before = os.fstat(descriptor)
        _assert_regular_file(before, max_bytes=max_bytes)
        output = bytearray()
        while len(output) <= max_bytes:
            chunk = os.read(descriptor, min(_CHUNK_SIZE, max_bytes + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
        after = os.fstat(descriptor)
        _assert_regular_file(after, max_bytes=max_bytes)
        if (
            (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or len(output) != after.st_size
        ):
            _blocked()
        return bytes(output)
    except VideoPrivateIOError:
        raise
    except OSError:
        _blocked()


def _git_preflight(relative_path: str) -> tuple[Path, bytes]:
    root = PROJECT_ROOT.resolve(strict=True)
    repository_path = f"{ARTIFACT_ROOT_RELATIVE.as_posix()}/{relative_path}"
    try:
        before = _git_status(root, _default_git)
        if _git_tracked_under_root(root, _default_git):
            _blocked()
        if not _git_ignored(root, _default_git, repository_path):
            _blocked()
    except VideoPrivateIOError:
        raise
    except (OSError, ValueError, VideoArtifactBoundaryError, subprocess.SubprocessError):
        _blocked()
    return root, before


def _git_postflight(root: Path, before: bytes) -> None:
    try:
        if _git_tracked_under_root(root, _default_git):
            _blocked()
        if _git_status(root, _default_git) != before:
            _blocked()
    except VideoPrivateIOError:
        raise
    except (OSError, ValueError, VideoArtifactBoundaryError, subprocess.SubprocessError):
        _blocked()


def _close(descriptor: int | None) -> None:
    if descriptor is not None:
        with suppress(OSError):
            os.close(descriptor)


def prepare_private_store() -> None:
    """Prepare and verify the fixed private store without exposing its path."""

    try:
        receipt = prepare_artifact_boundary()
        validate_public_receipt(receipt)
    except (VideoArtifactBoundaryError, OSError, ValueError):
        _blocked()


def read_private_bytes(
    relative_path: str | os.PathLike[str],
    max_bytes: int,
) -> bytes:
    """Read one owned, mode-0600, non-linked artifact below the private root."""

    _validate_max_bytes(max_bytes)
    parts = _safe_relative_parts(relative_path)
    chain: _DirectoryChain | None = None
    descriptor: int | None = None
    try:
        chain = _open_parent(parts, create=False)
        parent = chain.parent
        name = chain.target_name
        _revalidate_chain(chain)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        close_on_exec = getattr(os, "O_CLOEXEC", 0)
        if nofollow is None:
            _blocked()
        entry_before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        _assert_regular_file(entry_before, max_bytes=max_bytes)
        descriptor = os.open(
            name,
            os.O_RDONLY | nofollow | close_on_exec,
            dir_fd=parent,
        )
        descriptor_before = os.fstat(descriptor)
        _assert_entry_matches_fd(entry_before, descriptor_before, max_bytes=max_bytes)
        payload = _read_fd(descriptor, max_bytes)
        descriptor_after = os.fstat(descriptor)
        entry_after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        _assert_entry_matches_fd(entry_after, descriptor_after, max_bytes=max_bytes)
        _revalidate_chain(chain)
        return payload
    except VideoPrivateIOError:
        raise
    except OSError:
        _blocked()
    finally:
        _close(descriptor)
        _close_chain(chain)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VideoPrivateIOError("private video artifact operation blocked")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise VideoPrivateIOError("private video artifact operation blocked")


def read_private_json(
    relative_path: str | os.PathLike[str],
    max_bytes: int,
) -> Any:
    """Read strict UTF-8 JSON without duplicate keys or non-finite numbers."""

    try:
        raw = read_private_bytes(relative_path, max_bytes)
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except VideoPrivateIOError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError):
        _blocked()


def _canonical_json(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        raw = text.encode("utf-8")
    except (RecursionError, TypeError, ValueError, UnicodeError):
        _blocked()
    if len(raw) > MAX_PRIVATE_FILE_BYTES:
        _blocked()
    return raw


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        try:
            written = os.write(descriptor, view)
        except OSError:
            _blocked()
        if written <= 0:
            _blocked()
        view = view[written:]


def _temporary_name(parent: int) -> tuple[str, int]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        _blocked()
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    for _ in range(_TEMP_ATTEMPTS):
        name = ".tmp-video-semantics-" + secrets.token_hex(16)
        try:
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow | close_on_exec,
                _FILE_MODE,
                dir_fd=parent,
            )
            return name, descriptor
        except FileExistsError:
            continue
        except OSError:
            _blocked()
    _blocked()


def _remove_name(parent: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=parent)
        os.fsync(parent)
    except OSError:
        pass


def _publish_no_replace(
    parent: int,
    temp_name: str,
    target_name: str,
    expected: os.stat_result,
) -> os.stat_result:
    """Atomically claim target_name without replacing an existing directory entry."""

    linked = False
    try:
        temp_info = os.stat(temp_name, dir_fd=parent, follow_symlinks=False)
        _assert_regular_file(temp_info)
        if not _same_inode(temp_info, expected):
            _blocked()
        os.link(
            temp_name,
            target_name,
            src_dir_fd=parent,
            dst_dir_fd=parent,
            follow_symlinks=False,
        )
        linked = True
        os.fsync(parent)
        target = os.stat(target_name, dir_fd=parent, follow_symlinks=False)
        if not _same_inode(target, expected) or target.st_nlink != 2:
            _blocked()
        _assert_regular_file(target, expected_nlink=2)
        os.unlink(temp_name, dir_fd=parent)
        os.fsync(parent)
        final = os.stat(target_name, dir_fd=parent, follow_symlinks=False)
        _assert_regular_file(final)
        linked = False
        return final
    except VideoPrivateIOError:
        raise
    except FileExistsError:
        _blocked()
    except OSError:
        _blocked()
    finally:
        if linked:
            with suppress(OSError):
                os.unlink(target_name, dir_fd=parent)
                os.fsync(parent)


def _assert_published_target(
    parent: int,
    target_name: str,
    expected: os.stat_result,
    descriptor: int,
) -> None:
    """Revalidate the published name against the still-held source capability."""

    try:
        target = os.stat(target_name, dir_fd=parent, follow_symlinks=False)
        opened = os.fstat(descriptor)
        _assert_regular_file(target)
        _assert_regular_file(opened)
        if not _same_file_state(target, expected) or not _same_file_state(opened, expected):
            _blocked()
    except VideoPrivateIOError:
        raise
    except OSError:
        _blocked()


def write_private_bytes_atomic(
    relative_path: str | os.PathLike[str],
    payload: bytes,
) -> None:
    """Write one new private artifact atomically; existing targets are rejected."""

    if not isinstance(payload, bytes) or len(payload) > MAX_PRIVATE_FILE_BYTES:
        _blocked()
    parts = _safe_relative_parts(relative_path)
    relative = "/".join(parts)
    root, before = _git_preflight(relative)
    chain: _DirectoryChain | None = None
    descriptor: int | None = None
    temp_name: str | None = None
    published = False
    published_info: os.stat_result | None = None
    target_name_for_cleanup: str | None = None
    try:
        chain = _open_parent(parts, create=True)
        parent = chain.parent
        target_name = chain.target_name
        target_name_for_cleanup = target_name
        temp_name, descriptor = _temporary_name(parent)
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        _assert_regular_file(info)
        _revalidate_chain(chain)
        published_info = _publish_no_replace(parent, temp_name, target_name, info)
        temp_name = None
        published = True
        _assert_published_target(parent, target_name, published_info, descriptor)
        _revalidate_chain(chain)
        _assert_published_target(parent, target_name, published_info, descriptor)
        _git_postflight(root, before)
        _revalidate_chain(chain)
        _assert_published_target(parent, target_name, published_info, descriptor)
    except VideoPrivateIOError:
        if (
            published
            and chain is not None
            and target_name_for_cleanup
            and published_info is not None
        ):
            with suppress(OSError):
                parent = chain.parent
                os.unlink(target_name_for_cleanup, dir_fd=parent)
                os.fsync(parent)
        raise
    except OSError:
        _blocked()
    finally:
        _close(descriptor)
        if temp_name is not None and chain is not None:
            _remove_name(chain.parent, temp_name)
        _close_chain(chain)
        if published:
            # The postflight above is the authoritative drift check.  No
            # public receipt contains the private path or artifact identity.
            pass


def write_private_json_atomic(
    relative_path: str | os.PathLike[str],
    value: Any,
) -> None:
    """Write canonical finite JSON as one new private artifact."""

    write_private_bytes_atomic(relative_path, _canonical_json(value))


__all__ = [
    "MAX_PRIVATE_FILE_BYTES",
    "VideoPrivateIOError",
    "prepare_private_store",
    "read_private_bytes",
    "read_private_json",
    "write_private_bytes_atomic",
    "write_private_json_atomic",
]
