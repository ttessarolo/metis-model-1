"""Configured tenant aliases and immutable, content-derived Metis snapshots."""

from __future__ import annotations

import os
import stat
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_sha256

MAX_TENANT_FILES = 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TENANT_BYTES = 64 * 1024 * 1024
MAX_TENANT_ENTRIES = 8192
MAX_DIRECTORY_DEPTH = 32
_EXCLUDED_DIRECTORIES = frozenset(
    {".git", ".cache", ".venv", "build", "dist", "node_modules", "target", "venv"}
)


@dataclass(frozen=True)
class TenantGrant:
    alias: str
    tenant_id: str
    root: Path
    root_device: int
    root_inode: int


@dataclass(frozen=True)
class SnapshotFile:
    path: str
    content: bytes
    sha256: str

    @property
    def text(self) -> str:
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise BrainError("INVALID_TENANT", 409, "tenant source is not valid UTF-8") from error


@dataclass(frozen=True)
class ContextSnapshot:
    tenant_alias: str
    tenant_id: str
    root_device: int
    root_inode: int
    revision: str
    toolchain_binding: str
    files: tuple[SnapshotFile, ...]
    total_bytes: int

    def source_map(self) -> dict[str, str]:
        return {
            item.path: item.text
            for item in self.files
            if PurePosixPath(item.path).suffix == ".metis"
        }

    def public_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "tenant_alias": self.tenant_alias,
            "tenant_id": self.tenant_id,
            "revision": self.revision,
            "toolchain_binding": self.toolchain_binding,
            "file_count": len(self.files),
            "total_bytes": self.total_bytes,
            "files": [
                {
                    "path": item.path,
                    "sha256": item.sha256,
                    "bytes": len(item.content),
                }
                for item in self.files
            ],
        }


def _root_identity(path: Path) -> tuple[int, int]:
    try:
        value = path.lstat()
    except OSError as error:
        raise BrainError("TENANT_UNAVAILABLE", 409, "tenant root is unavailable") from error
    if path.is_symlink() or not stat.S_ISDIR(value.st_mode):
        raise BrainError("INVALID_TENANT", 409, "tenant root must be a real directory")
    return value.st_dev, value.st_ino


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


def _stable_regular_bytes_at(
    directory_fd: int,
    name: str,
    before: os.stat_result,
    *,
    label: str,
) -> bytes:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size > MAX_FILE_BYTES
        ):
            raise BrainError("INVALID_TENANT", 409, f"{label} is not a bounded regular file")
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
        named_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except BrainError:
        raise
    except OSError as error:
        raise BrainError("TENANT_UNAVAILABLE", 409, f"{label} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)

    if (
        _stat_identity(before) != _stat_identity(opened)
        or _stat_identity(opened) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(named_after)
        or len(raw) != opened.st_size
    ):
        raise BrainError("STALE_CONTEXT", 409, f"{label} changed while it was read")
    return raw


def _validate_tenant_toml(raw: bytes, *, expected_id: str) -> None:
    try:
        value = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise BrainError("INVALID_TENANT", 409, "metis.toml is invalid") from error
    tenant = value.get("tenant") if isinstance(value, dict) else None
    if not isinstance(tenant, dict) or tenant.get("id") != expected_id:
        raise BrainError("INVALID_TENANT", 409, "metis.toml tenant identity differs from grant")


class TenantRegistry:
    """Server-owned alias map; request data can never choose a filesystem root."""

    def __init__(self, grants: list[tuple[str, str, Path]]) -> None:
        if not grants:
            raise BrainError("INVALID_CONFIG", 500, "at least one tenant grant is required")
        normalized: dict[str, TenantGrant] = {}
        for alias, tenant_id, raw_root in grants:
            if alias in normalized:
                raise BrainError("INVALID_CONFIG", 500, "tenant aliases must be distinct")
            root_value = Path(raw_root)
            if not root_value.is_absolute():
                raise BrainError("INVALID_CONFIG", 500, "tenant roots must be absolute")
            try:
                root = root_value.resolve(strict=True)
            except OSError as error:
                raise BrainError("INVALID_CONFIG", 500, "tenant root is unavailable") from error
            if root != root_value:
                raise BrainError("INVALID_CONFIG", 500, "tenant root must be canonical")
            device, inode = _root_identity(root)
            if not alias or len(alias) > 64 or not tenant_id or len(tenant_id) > 128:
                raise BrainError("INVALID_CONFIG", 500, "tenant grant identity is invalid")
            normalized[alias] = TenantGrant(alias, tenant_id, root, device, inode)
        self._grants = normalized

    @property
    def aliases(self) -> frozenset[str]:
        return frozenset(self._grants)

    def grant(self, alias: str) -> TenantGrant:
        try:
            return self._grants[alias]
        except KeyError as error:
            raise BrainError(
                "TENANT_NOT_AUTHORIZED", 403, "tenant alias is not authorized"
            ) from error

    def capture(self, alias: str, *, toolchain_binding: str) -> ContextSnapshot:
        grant = self.grant(alias)
        if _root_identity(grant.root) != (grant.root_device, grant.root_inode):
            raise BrainError("STALE_CONTEXT", 409, "tenant root identity changed")

        root_descriptor: int | None = None
        records: list[SnapshotFile] = []
        total = 0
        entries = 0

        def walk(directory_fd: int, parts: tuple[str, ...]) -> None:
            nonlocal entries, total
            if len(parts) > MAX_DIRECTORY_DEPTH:
                raise BrainError("INVALID_TENANT", 409, "tenant directory depth exceeds limit")
            try:
                names = sorted(os.listdir(directory_fd))
            except OSError as error:
                raise BrainError(
                    "TENANT_UNAVAILABLE", 409, "tenant cannot be enumerated"
                ) from error
            for name in names:
                entries += 1
                if entries > MAX_TENANT_ENTRIES:
                    raise BrainError("INVALID_TENANT", 409, "tenant entry count exceeds limit")
                try:
                    name.encode("utf-8")
                except UnicodeEncodeError as error:
                    raise BrainError("INVALID_TENANT", 409, "tenant path is not UTF-8") from error
                try:
                    item_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                except OSError as error:
                    raise BrainError(
                        "STALE_CONTEXT", 409, "tenant entry changed during enumeration"
                    ) from error
                if stat.S_ISLNK(item_stat.st_mode):
                    raise BrainError("INVALID_TENANT", 409, "tenant contains a symbolic link")
                if stat.S_ISDIR(item_stat.st_mode):
                    if name in _EXCLUDED_DIRECTORIES or name.startswith(".env"):
                        continue
                    child: int | None = None
                    try:
                        child = os.open(
                            name,
                            os.O_RDONLY
                            | os.O_DIRECTORY
                            | os.O_NOFOLLOW
                            | getattr(os, "O_CLOEXEC", 0),
                            dir_fd=directory_fd,
                        )
                        if _stat_identity(item_stat) != _stat_identity(os.fstat(child)):
                            raise BrainError(
                                "STALE_CONTEXT", 409, "tenant directory changed during open"
                            )
                        walk(child, (*parts, name))
                        named_after = os.stat(
                            name,
                            dir_fd=directory_fd,
                            follow_symlinks=False,
                        )
                        if _stat_identity(item_stat) != _stat_identity(named_after):
                            raise BrainError(
                                "STALE_CONTEXT", 409, "tenant directory changed during read"
                            )
                    except BrainError:
                        raise
                    except OSError as error:
                        raise BrainError(
                            "STALE_CONTEXT", 409, "tenant directory changed during traversal"
                        ) from error
                    finally:
                        if child is not None:
                            os.close(child)
                    continue
                if not stat.S_ISREG(item_stat.st_mode):
                    raise BrainError("INVALID_TENANT", 409, "tenant contains a special file")
                relative_parts = (*parts, name)
                if name.startswith(".env") or any(
                    part.startswith(".env") for part in relative_parts
                ):
                    continue
                relative = PurePosixPath(*relative_parts).as_posix()
                if relative != "metis.toml" and PurePosixPath(relative).suffix != ".metis":
                    continue
                if len(records) >= MAX_TENANT_FILES:
                    raise BrainError("INVALID_TENANT", 409, "tenant file roster is invalid")
                raw = _stable_regular_bytes_at(
                    directory_fd,
                    name,
                    item_stat,
                    label="tenant source",
                )
                try:
                    raw.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise BrainError("INVALID_TENANT", 409, "tenant source is not UTF-8") from error
                total += len(raw)
                if total > MAX_TENANT_BYTES:
                    raise BrainError("INVALID_TENANT", 409, "tenant exceeds snapshot byte cap")
                records.append(SnapshotFile(relative, raw, bytes_sha256(raw)))

        try:
            root_descriptor = os.open(
                grant.root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            )
            opened_root = os.fstat(root_descriptor)
            if (opened_root.st_dev, opened_root.st_ino) != (
                grant.root_device,
                grant.root_inode,
            ):
                raise BrainError("STALE_CONTEXT", 409, "tenant root identity changed")
            walk(root_descriptor, ())
            after_root = os.fstat(root_descriptor)
            if _stat_identity(opened_root) != _stat_identity(after_root):
                raise BrainError("STALE_CONTEXT", 409, "tenant root changed during snapshot")
        except BrainError:
            raise
        except OSError as error:
            raise BrainError("TENANT_UNAVAILABLE", 409, "tenant cannot be enumerated") from error
        finally:
            if root_descriptor is not None:
                os.close(root_descriptor)

        records.sort(key=lambda item: item.path)
        if not records:
            raise BrainError("INVALID_TENANT", 409, "tenant file roster is invalid")

        toml_records = [item for item in records if item.path == "metis.toml"]
        if len(toml_records) != 1:
            raise BrainError("INVALID_TENANT", 409, "tenant requires one root metis.toml")
        _validate_tenant_toml(toml_records[0].content, expected_id=grant.tenant_id)
        if _root_identity(grant.root) != (grant.root_device, grant.root_inode):
            raise BrainError("STALE_CONTEXT", 409, "tenant root identity changed")

        revision = canonical_sha256(
            {
                "schema_version": 1,
                "tenant_alias": grant.alias,
                "tenant_id": grant.tenant_id,
                "root_identity": {"device": grant.root_device, "inode": grant.root_inode},
                "toolchain_binding": toolchain_binding,
                "files": [
                    {"path": item.path, "bytes": len(item.content), "sha256": item.sha256}
                    for item in records
                ],
            }
        )
        return ContextSnapshot(
            tenant_alias=grant.alias,
            tenant_id=grant.tenant_id,
            root_device=grant.root_device,
            root_inode=grant.root_inode,
            revision=revision,
            toolchain_binding=toolchain_binding,
            files=tuple(records),
            total_bytes=total,
        )

    def assert_current(self, snapshot: ContextSnapshot) -> None:
        current = self.capture(
            snapshot.tenant_alias,
            toolchain_binding=snapshot.toolchain_binding,
        )
        if current.revision != snapshot.revision:
            raise BrainError("STALE_CONTEXT", 409, "tenant context changed")


def toolchain_binding_from_pin(pin: Mapping[str, Any]) -> str:
    required = {"revision", "tree", "language_version"}
    if not required.issubset(pin) or any(not isinstance(pin[item], str) for item in required):
        raise BrainError("INVALID_CONFIG", 500, "toolchain pin identity is invalid")
    return canonical_sha256(dict(pin))
