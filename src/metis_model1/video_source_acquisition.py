"""Read-only acquisition of a private video-semantics source roster.

The acquisition boundary deliberately returns hashes and opaque ordinal
identifiers in the canonical manifest.  Human-readable locators are kept in a
separate in-memory registry so the caller can hand that object to a private
store without ever putting it in a public receipt or a model prompt.

This module never persists, logs, downloads, contacts a tenant, or reads a
credential.  Its only filesystem operation is a bounded, fail-closed read of
the explicitly supplied root.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
import time
import uuid
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from metis_model1.video_semantics_contracts import (
    manifest_digest,
    semantic_source_revision,
    validate_acquisition_receipt,
    validate_source_manifest,
)

SCHEMA_VERSION = 1
MANIFEST_ID = "video-semantics/sources-v1"
RECEIPT_ROSTER_ID = "video-semantics/acquisition-receipts-v1"
LOCATOR_REGISTRY_ID = "video-semantics/private-locators-v1"
PRIVATE_TENANT = "tenant-video-private-v1"
CATALOG = "video"
SOURCE_KIND = "reserved_editorial"
IDENTITY_STORAGE = "local-confidential-receipt"
SENSITIVITY = "internal_editorial"
TOOL_VERSION = "video-source-acquisition-v1"
ARTIFACT_KIND = "video-source-acquisition-bundle-v1"
IGNORED_HIDDEN_ENTRIES = frozenset({".DS_Store", ".localized"})
SUPPORTED_SOURCE_FORMATS = frozenset({"pdf", "txt", "md", "doc", "docx", "rtf", "odt"})
_FORBIDDEN_SOURCE_NAMES = frozenset(
    {"credentials", "credential", "secrets", "secret", "id_rsa", "id_ed25519"}
)
_FORBIDDEN_SOURCE_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".kdbx"})
_FORBIDDEN_SOURCE_TOKEN = re.compile(
    r"(?:^|[^a-z0-9])(?:credentials?|secrets?|id[_-]?(?:rsa|ed25519))(?:[^a-z0-9]|$)"
)

MAX_FILES = 128
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_DEPTH = 32
MAX_DIRECTORIES = 512
HASH_CHUNK_BYTES = 1024 * 1024

PUBLIC_KEYS = frozenset(
    {
        "schema_version",
        "operation",
        "status",
        "private_roster_complete",
        "gaps",
        "sensitivity",
        "raw_payloads_present",
        "error_codes",
    }
)
ERROR_CODES = frozenset(
    {
        "ROOT_NOT_ABSOLUTE",
        "ROOT_MISSING",
        "ROOT_SYMLINK",
        "ROOT_NOT_DIRECTORY",
        "ROOT_WRONG_OWNER",
        "ROOT_UNSAFE",
        "EMPTY_ROOT",
        "SYMLINK_ENTRY",
        "HARDLINK_ENTRY",
        "DEVICE_ENTRY",
        "NONREGULAR_ENTRY",
        "MAX_FILES_EXCEEDED",
        "MAX_FILE_BYTES_EXCEEDED",
        "MAX_TOTAL_BYTES_EXCEEDED",
        "MAX_DEPTH_EXCEEDED",
        "MAX_DIRECTORIES_EXCEEDED",
        "SOURCE_DRIFT",
        "SOURCE_UNREADABLE",
        "MANIFEST_INVALID",
        "RECEIPT_INVALID",
        "REGISTRY_INVALID",
        "INVALID_RUN_ID",
        "HIDDEN_ENTRY",
        "FORMAT_UNSUPPORTED",
        "SENSITIVE_NAME_FORBIDDEN",
        "BUNDLE_INVALID",
    }
)


class VideoSourceAcquisitionError(ValueError):
    """A safe, non-descriptive acquisition failure.

    The exception intentionally contains only an allowlisted error code.  It
    never includes a path, filename, hash, file size, or source content.
    """

    def __init__(self, code: str) -> None:
        if code not in ERROR_CODES:
            code = "ROOT_UNSAFE"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class VideoSourceBundle:
    """Private in-memory documents plus the only public-safe result."""

    manifest: Mapping[str, Any]
    receipt_roster: Mapping[str, Any]
    locator_registry: Mapping[str, Any]
    public_result: Mapping[str, Any]

    @property
    def receipts(self) -> tuple[Mapping[str, Any], ...]:
        """Compatibility view of the private receipt entries."""

        return tuple(self.receipt_roster["receipts"])


@dataclass(frozen=True)
class _SourceFile:
    relative_path: str
    name: str
    format: str
    size_bytes: int
    content_sha256: str


@dataclass(frozen=True)
class _DirectoryCapability:
    path: Path
    name: str | None
    descriptor: int
    parent_descriptor: int | None
    expected: os.stat_result


def _current_uid() -> int:
    getuid = getattr(os, "getuid", None)
    if not callable(getuid):
        raise VideoSourceAcquisitionError("ROOT_UNSAFE")
    return int(getuid())


def _public_result(
    *, status: str, complete: bool, gaps: int, error_codes: tuple[str, ...] = ()
) -> Mapping[str, Any]:
    codes = tuple(sorted(set(error_codes)))
    if not set(codes) <= ERROR_CODES:
        raise AssertionError("unknown acquisition error code")
    result = {
        "schema_version": SCHEMA_VERSION,
        "operation": "acquire-video-source-roster",
        "status": status,
        "private_roster_complete": complete,
        "gaps": max(0, gaps),
        "sensitivity": SENSITIVITY,
        "raw_payloads_present": False,
        "error_codes": list(codes),
    }
    if set(result) != PUBLIC_KEYS:
        raise AssertionError("public acquisition result is not allowlisted")
    return result


def _raise(code: str) -> None:
    raise VideoSourceAcquisitionError(code)


def _root_stat(root: Path) -> os.stat_result:
    if not root.is_absolute():
        _raise("ROOT_NOT_ABSOLUTE")
    try:
        info = os.lstat(root)
    except FileNotFoundError:
        _raise("ROOT_MISSING")
    except OSError:
        _raise("ROOT_UNSAFE")
    if stat.S_ISLNK(info.st_mode):
        _raise("ROOT_SYMLINK")
    if not stat.S_ISDIR(info.st_mode):
        _raise("ROOT_NOT_DIRECTORY")
    if info.st_uid != _current_uid():
        _raise("ROOT_WRONG_OWNER")
    if info.st_mode & 0o022:
        _raise("ROOT_UNSAFE")
    return info


def _same_stat(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_mode,
        before.st_dev,
        before.st_ino,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_mode,
        after.st_dev,
        after.st_ino,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )


def _same_directory_identity_security(before: os.stat_result, after: os.stat_result) -> bool:
    """Compare directory identity and security state, not mutable counters.

    Ancestor directories are held by descriptor throughout acquisition.  A
    harmless sibling creation changes their link count and timestamps, but it
    does not change the directory identity or its security boundary.  Those
    mutable fields therefore must not turn a stable capability into a false
    source-drift failure.  The source root itself is still checked with
    ``_same_stat`` by ``_revalidate_directory_chain``.
    """

    return (
        stat.S_IFMT(before.st_mode),
        stat.S_IMODE(before.st_mode),
        before.st_dev,
        before.st_ino,
        before.st_uid,
        before.st_gid,
    ) == (
        stat.S_IFMT(after.st_mode),
        stat.S_IMODE(after.st_mode),
        after.st_dev,
        after.st_ino,
        after.st_uid,
        after.st_gid,
    )


def _open_absolute_directory_chain(root: Path) -> tuple[_DirectoryCapability, ...]:
    """Hold and fingerprint every directory from the filesystem root to ``root``."""

    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if not root.is_absolute() or nofollow is None or directory_flag is None:
        _raise("ROOT_UNSAFE")
    flags = os.O_RDONLY | nofollow | directory_flag | getattr(os, "O_CLOEXEC", 0)
    chain: list[_DirectoryCapability] = []
    try:
        anchor = Path(root.anchor)
        anchor_entry = anchor.lstat()
        anchor_fd = os.open(anchor, flags)
        anchor_opened = os.fstat(anchor_fd)
        if (
            not stat.S_ISDIR(anchor_entry.st_mode)
            or stat.S_ISLNK(anchor_entry.st_mode)
            or anchor_entry.st_uid not in {0, _current_uid()}
            or not _same_stat(anchor_entry, anchor_opened)
        ):
            os.close(anchor_fd)
            _raise("ROOT_UNSAFE")
        chain.append(_DirectoryCapability(anchor, None, anchor_fd, None, anchor_opened))
        current = anchor
        path_parts = root.parts[1:]
        for index, name in enumerate(path_parts):
            parent_fd = chain[-1].descriptor
            entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            descriptor = os.open(name, flags, dir_fd=parent_fd)
            opened = os.fstat(descriptor)
            current = current / name
            same_state = (
                _same_stat if index == len(path_parts) - 1 else _same_directory_identity_security
            )
            if (
                not stat.S_ISDIR(entry.st_mode)
                or stat.S_ISLNK(entry.st_mode)
                or entry.st_uid not in {0, _current_uid()}
                or (index == len(path_parts) - 1 and entry.st_mode & 0o022)
                or (index == len(path_parts) - 1 and opened.st_mode & 0o022)
                or not same_state(entry, opened)
            ):
                os.close(descriptor)
                _raise("SOURCE_DRIFT")
            chain.append(_DirectoryCapability(current, name, descriptor, parent_fd, opened))
        return tuple(chain)
    except VideoSourceAcquisitionError:
        for item in reversed(chain):
            os.close(item.descriptor)
        raise
    except OSError:
        for item in reversed(chain):
            os.close(item.descriptor)
        _raise("ROOT_UNSAFE")


def _revalidate_directory_chain(chain: tuple[_DirectoryCapability, ...]) -> None:
    try:
        for index, item in enumerate(chain):
            opened = os.fstat(item.descriptor)
            entry = item.path.lstat()
            same_state = (
                _same_stat if index == len(chain) - 1 else _same_directory_identity_security
            )
            if (
                not same_state(item.expected, opened)
                or not same_state(item.expected, entry)
                or not stat.S_ISDIR(entry.st_mode)
                or stat.S_ISLNK(entry.st_mode)
            ):
                _raise("SOURCE_DRIFT")
            if item.parent_descriptor is not None and item.name is not None:
                child = os.stat(
                    item.name,
                    dir_fd=item.parent_descriptor,
                    follow_symlinks=False,
                )
                if not same_state(item.expected, child):
                    _raise("SOURCE_DRIFT")
    except VideoSourceAcquisitionError:
        raise
    except OSError:
        _raise("SOURCE_DRIFT")


def _close_directory_chain(chain: tuple[_DirectoryCapability, ...]) -> None:
    for item in reversed(chain):
        with suppress(OSError):
            os.close(item.descriptor)


def _format_for(path: Path) -> str:
    suffixes = path.suffixes
    return ".".join(suffix.lstrip(".").lower() for suffix in suffixes if suffix != ".") or "none"


def _validated_source_format(name: str) -> str:
    lowered = name.casefold()
    stem = Path(lowered).stem
    suffix = Path(lowered).suffix
    if (
        lowered in _FORBIDDEN_SOURCE_NAMES
        or stem in _FORBIDDEN_SOURCE_NAMES
        or suffix in _FORBIDDEN_SOURCE_SUFFIXES
        or _FORBIDDEN_SOURCE_TOKEN.search(lowered) is not None
    ):
        _raise("SENSITIVE_NAME_FORBIDDEN")
    source_format = _format_for(Path(name))
    if source_format not in SUPPORTED_SOURCE_FORMATS:
        _raise("FORMAT_UNSUPPORTED")
    return source_format


def _hash_regular_file(parent_fd: int, name: str, expected: os.stat_result) -> str:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        _raise("ROOT_UNSAFE")
    flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError:
        _raise("SOURCE_UNREADABLE")
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            _raise(
                "DEVICE_ENTRY"
                if stat.S_ISCHR(opened.st_mode) or stat.S_ISBLK(opened.st_mode)
                else "NONREGULAR_ENTRY"
            )
        if opened.st_nlink != 1:
            _raise("HARDLINK_ENTRY")
        if opened.st_uid != _current_uid():
            _raise("ROOT_WRONG_OWNER")
        if opened.st_mode & 0o022:
            _raise("ROOT_UNSAFE")
        if not _same_stat(expected, opened):
            _raise("SOURCE_DRIFT")
        if opened.st_size > MAX_FILE_BYTES:
            _raise("MAX_FILE_BYTES_EXCEEDED")
        digest = hashlib.sha256()
        while True:
            try:
                chunk = os.read(fd, HASH_CHUNK_BYTES)
            except OSError:
                _raise("SOURCE_UNREADABLE")
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fd)
        if not _same_stat(opened, after):
            _raise("SOURCE_DRIFT")
        try:
            path_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            _raise("SOURCE_DRIFT")
        if not _same_stat(after, path_after) or stat.S_ISLNK(path_after.st_mode):
            _raise("SOURCE_DRIFT")
        return "sha256:" + digest.hexdigest()
    finally:
        os.close(fd)


def _walk_sources(root_capability: _DirectoryCapability) -> tuple[_SourceFile, ...]:
    records: list[_SourceFile] = []
    total = 0
    directories = 0
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_flag is None:
        _raise("ROOT_UNSAFE")

    def open_directory(parent_fd: int | None, name: str | None, expected: os.stat_result) -> int:
        flags = os.O_RDONLY | nofollow | directory_flag | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = (
                os.dup(root_capability.descriptor)
                if name is None
                else os.open(name, flags, dir_fd=parent_fd)
            )
            opened = os.fstat(fd)
        except OSError:
            _raise("SOURCE_UNREADABLE")
        if (
            not _same_stat(expected, opened)
            or not stat.S_ISDIR(opened.st_mode)
            or opened.st_mode & 0o022
        ):
            os.close(fd)
            _raise("ROOT_UNSAFE" if opened.st_mode & 0o022 else "SOURCE_DRIFT")
        if opened.st_uid != _current_uid():
            os.close(fd)
            _raise("ROOT_WRONG_OWNER")
        return fd

    def visit(
        parent_fd: int | None,
        name: str | None,
        relative_prefix: str,
        expected: os.stat_result,
        depth: int,
    ) -> None:
        nonlocal total, directories
        if depth > MAX_DEPTH:
            _raise("MAX_DEPTH_EXCEEDED")
        directories += 1
        if directories > MAX_DIRECTORIES:
            _raise("MAX_DIRECTORIES_EXCEEDED")
        directory_fd = open_directory(parent_fd, name, expected)
        try:
            try:
                with os.scandir(directory_fd) as iterator:
                    entries = sorted(iterator, key=lambda entry: entry.name)
            except OSError:
                _raise("SOURCE_UNREADABLE")
            for entry in entries:
                if entry.name in IGNORED_HIDDEN_ENTRIES:
                    continue
                if entry.name.startswith("."):
                    _raise("HIDDEN_ENTRY")
                try:
                    info = os.stat(entry.name, dir_fd=directory_fd, follow_symlinks=False)
                except OSError:
                    _raise("SOURCE_UNREADABLE")
                if stat.S_ISLNK(info.st_mode):
                    _raise("SYMLINK_ENTRY")
                child_relative = (
                    f"{relative_prefix}/{entry.name}" if relative_prefix else entry.name
                )
                if stat.S_ISDIR(info.st_mode):
                    if info.st_mode & 0o022:
                        _raise("ROOT_UNSAFE")
                    visit(directory_fd, entry.name, child_relative, info, depth + 1)
                    continue
                if stat.S_ISCHR(info.st_mode) or stat.S_ISBLK(info.st_mode):
                    _raise("DEVICE_ENTRY")
                if not stat.S_ISREG(info.st_mode):
                    _raise("NONREGULAR_ENTRY")
                if info.st_mode & 0o022:
                    _raise("ROOT_UNSAFE")
                if info.st_nlink != 1:
                    _raise("HARDLINK_ENTRY")
                if info.st_uid != _current_uid():
                    _raise("ROOT_WRONG_OWNER")
                if info.st_size > MAX_FILE_BYTES:
                    _raise("MAX_FILE_BYTES_EXCEEDED")
                if len(records) >= MAX_FILES:
                    _raise("MAX_FILES_EXCEEDED")
                if total + info.st_size > MAX_TOTAL_BYTES:
                    _raise("MAX_TOTAL_BYTES_EXCEEDED")
                source_format = _validated_source_format(entry.name)
                digest = _hash_regular_file(directory_fd, entry.name, info)
                records.append(
                    _SourceFile(
                        relative_path=child_relative,
                        name=entry.name,
                        format=source_format,
                        size_bytes=info.st_size,
                        content_sha256=digest,
                    )
                )
                total += info.st_size
            if not _same_stat(expected, os.fstat(directory_fd)):
                _raise("SOURCE_DRIFT")
        finally:
            os.close(directory_fd)

    visit(None, None, "", root_capability.expected, 0)
    # Identity is deliberately content-addressed.  The registry remains path
    # ordered, but renaming/reordering files does not change semantic revision.
    records.sort(key=lambda item: item.content_sha256)
    if not records:
        _raise("EMPTY_ROOT")
    return tuple(records)


def _validate_run_id(run_id: str) -> None:
    if not isinstance(run_id, str) or not (8 <= len(run_id) <= 96):
        _raise("INVALID_RUN_ID")
    if not all(char.isalnum() or char in "_-" for char in run_id):
        _raise("INVALID_RUN_ID")


def _documents(
    records: tuple[_SourceFile, ...], run_id: str, root_locator: str
) -> VideoSourceBundle:
    sources: list[dict[str, Any]] = []
    registry_entries: list[dict[str, Any]] = []
    manifest_time = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for index, record in enumerate(records, start=1):
        source_id = f"source-{index:06d}"
        source_ref = f"source-ref-{index:06d}"
        sources.append(
            {
                "source_id": source_id,
                "source_ref": source_ref,
                "kind": SOURCE_KIND,
                "identity_storage": IDENTITY_STORAGE,
                "repository_commit": None,
                "tenant": PRIVATE_TENANT,
                "catalog": CATALOG,
                "sensitivity": SENSITIVITY,
                "manifest_schema": SCHEMA_VERSION,
                "content_sha256": record.content_sha256,
            }
        )
        registry_entries.append(
            {
                "source_id": source_id,
                "source_ref": source_ref,
                "locator": record.relative_path,
                "name": record.name,
                "format": record.format,
                "size_bytes": record.size_bytes,
            }
        )
    registry_entries.sort(key=lambda entry: entry["locator"])
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "manifest_id": MANIFEST_ID,
        "semantic_source_revision": "",
        "sources": sources,
    }
    manifest["semantic_source_revision"] = semantic_source_revision(manifest)
    manifest_errors = validate_source_manifest(manifest)
    if manifest_errors:
        _raise("MANIFEST_INVALID")
    manifest_sha = manifest_digest(manifest)
    receipts: list[dict[str, Any]] = []
    started = time.monotonic()
    for index, source in enumerate(sources, start=1):
        receipt: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "receipt_id": f"receipt-{index:06d}",
            "manifest_sha256": manifest_sha,
            "source_id": source["source_id"],
            "status": "VALID",
            "acquired_at": manifest_time,
            "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
            "run_id": run_id,
            "runtime": {"python": sys.version.split()[0], "tool_version": TOOL_VERSION},
            "counts": {"items_in": 1, "items_out": 1, "items_distinct": 1, "items_gaps": 0},
        }
        receipt["receipt_sha256"] = manifest_digest(receipt)
        if validate_acquisition_receipt(receipt, manifest):
            _raise("RECEIPT_INVALID")
        receipts.append(receipt)
    registry: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "registry_id": LOCATOR_REGISTRY_ID,
        "manifest_sha256": manifest_sha,
        "root_locator": root_locator,
        "entries": registry_entries,
    }
    receipt_roster: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "roster_id": RECEIPT_ROSTER_ID,
        "manifest_sha256": manifest_sha,
        "receipts": receipts,
    }
    if not _receipt_roster_valid(receipt_roster, manifest, manifest_sha):
        _raise("RECEIPT_INVALID")
    if not _registry_valid(registry, sources, manifest_sha):
        _raise("REGISTRY_INVALID")
    public = _public_result(status="VALID", complete=True, gaps=0)
    return VideoSourceBundle(
        manifest=manifest,
        receipt_roster=receipt_roster,
        locator_registry=registry,
        public_result=public,
    )


def _receipt_roster_valid(
    roster: Mapping[str, Any], manifest: Mapping[str, Any], manifest_sha: str
) -> bool:
    if set(roster) != {"schema_version", "roster_id", "manifest_sha256", "receipts"}:
        return False
    if (
        type(roster.get("schema_version")) is not int
        or roster.get("schema_version") != SCHEMA_VERSION
        or roster.get("roster_id") != RECEIPT_ROSTER_ID
        or roster.get("manifest_sha256") != manifest_sha
        or not isinstance(roster.get("receipts"), list)
    ):
        return False
    receipts = roster["receipts"]
    if len(manifest["sources"]) > MAX_FILES or len(receipts) > MAX_FILES:
        return False
    source_ids = {source["source_id"] for source in manifest["sources"]}
    observed: set[str] = set()
    for receipt in receipts:
        if not isinstance(receipt, dict) or validate_acquisition_receipt(receipt, manifest):
            return False
        source_id = receipt["source_id"]
        if source_id in observed or source_id not in source_ids:
            return False
        observed.add(source_id)
    return observed == source_ids


def _registry_valid(
    registry: Mapping[str, Any], sources: list[dict[str, Any]], manifest_sha: str
) -> bool:
    if set(registry) != {
        "schema_version",
        "registry_id",
        "manifest_sha256",
        "root_locator",
        "entries",
    }:
        return False
    if (
        type(registry.get("schema_version")) is not int
        or registry.get("schema_version") != SCHEMA_VERSION
        or registry.get("registry_id") != LOCATOR_REGISTRY_ID
    ):
        return False
    if registry.get("manifest_sha256") != manifest_sha:
        return False
    root_locator = registry.get("root_locator")
    if (
        not isinstance(root_locator, str)
        or not root_locator
        or not Path(root_locator).is_absolute()
    ):
        return False
    entries = registry.get("entries")
    if not isinstance(entries, list) or len(entries) != len(sources) or len(entries) > MAX_FILES:
        return False
    source_keys = {(source["source_id"], source["source_ref"]) for source in sources}
    observed: set[tuple[Any, Any]] = set()
    locators: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            return False
        if set(entry) != {"source_id", "source_ref", "locator", "name", "format", "size_bytes"}:
            return False
        key = (entry["source_id"], entry["source_ref"])
        if key not in source_keys or key in observed:
            return False
        if not all(
            isinstance(entry[field], str) and entry[field]
            for field in ("locator", "name", "format")
        ):
            return False
        locator = entry["locator"]
        parts = locator.split("/")
        if (
            locator.startswith("/")
            or "\\" in locator
            or any(part in ("", ".", "..") for part in parts)
            or len(parts) > MAX_DEPTH + 1
            or entry["name"] != parts[-1]
            or entry["format"] != _format_for(Path(entry["name"]))
            or locator in locators
        ):
            return False
        if (
            not isinstance(entry["size_bytes"], int)
            or isinstance(entry["size_bytes"], bool)
            or entry["size_bytes"] < 0
        ):
            return False
        observed.add(key)
        locators.add(locator)
    return observed == source_keys


def acquire_video_source_roster(root: Path, *, run_id: str | None = None) -> VideoSourceBundle:
    """Acquire a bounded private source roster from ``root`` without persistence.

    ``root`` is a capability supplied by the caller.  The returned manifest,
    receipt roster, and locator registry are private objects intended for a
    later secure store; only ``bundle.public_result`` is safe to expose.
    """

    root = Path(root)
    initial_root = _root_stat(root)
    try:
        canonical_root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        _raise("ROOT_UNSAFE")
    canonical_info = _root_stat(canonical_root)
    if not _same_stat(initial_root, canonical_info):
        _raise("SOURCE_DRIFT")
    resolved_run_id = run_id or f"acq-{uuid.uuid4().hex}"
    _validate_run_id(resolved_run_id)
    chain = _open_absolute_directory_chain(canonical_root)
    try:
        _revalidate_directory_chain(chain)
        records = _walk_sources(chain[-1])
        _revalidate_directory_chain(chain)
        bundle = _documents(records, resolved_run_id, os.fspath(canonical_root))
        _revalidate_directory_chain(chain)
        return bundle
    finally:
        _close_directory_chain(chain)


def public_failure(error: VideoSourceAcquisitionError) -> Mapping[str, Any]:
    """Convert a failed acquisition into the allowlisted public contract."""

    return _public_result(status="INVALID", complete=False, gaps=1, error_codes=(error.code,))


def _bundle_body(document: Mapping[str, Any]) -> dict[str, Any]:
    return {key: document[key] for key in document if key != "bundle_sha256"}


def private_bundle_document(bundle: VideoSourceBundle) -> Mapping[str, Any]:
    """Build one atomic private envelope for the three acquisition documents."""

    if not isinstance(bundle, VideoSourceBundle):
        _raise("BUNDLE_INVALID")
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "manifest": dict(bundle.manifest),
        "receipt_roster": dict(bundle.receipt_roster),
        "locator_registry": dict(bundle.locator_registry),
        "bundle_sha256": "",
    }
    document["bundle_sha256"] = manifest_digest(_bundle_body(document))
    validate_private_bundle_document(document)
    return document


def validate_private_bundle_document(value: Any) -> bool:
    """Validate an envelope without returning any sensitive diagnostics."""

    try:
        if not isinstance(value, Mapping):
            _raise("BUNDLE_INVALID")
        if set(value) != {
            "schema_version",
            "artifact_kind",
            "manifest",
            "receipt_roster",
            "locator_registry",
            "bundle_sha256",
        }:
            _raise("BUNDLE_INVALID")
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != SCHEMA_VERSION
            or value["artifact_kind"] != ARTIFACT_KIND
        ):
            _raise("BUNDLE_INVALID")
        bundle_hash = value["bundle_sha256"]
        if not isinstance(bundle_hash, str) or bundle_hash != manifest_digest(_bundle_body(value)):
            _raise("BUNDLE_INVALID")
        manifest = value["manifest"]
        if not isinstance(manifest, Mapping) or validate_source_manifest(manifest):
            _raise("BUNDLE_INVALID")
        manifest_sha = manifest_digest(manifest)
        roster = value["receipt_roster"]
        if not isinstance(roster, Mapping) or not _receipt_roster_valid(
            roster, manifest, manifest_sha
        ):
            _raise("BUNDLE_INVALID")
        registry = value["locator_registry"]
        if not isinstance(registry, Mapping) or not _registry_valid(
            registry, list(manifest["sources"]), manifest_sha
        ):
            _raise("BUNDLE_INVALID")
        return True
    except VideoSourceAcquisitionError:
        raise
    except Exception:
        _raise("BUNDLE_INVALID")
    return False
