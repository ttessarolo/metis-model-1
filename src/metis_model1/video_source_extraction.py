"""Fail-closed local extraction of a validated private source bundle.

The bundle contract is the private acquisition document produced by the
acquisition lane: manifest, receipt roster, and locator registry.  Extraction
is deterministic and read-only.  Raw text exists only in the returned private
envelope; the public result contains no paths, identifiers, hashes, stderr, or
source payload.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import select
import socket
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from metis_model1.video_private_artifacts import _current_uid as _current_uid
from metis_model1.video_private_io import MAX_PRIVATE_FILE_BYTES
from metis_model1.video_semantics_contracts import manifest_digest
from metis_model1.video_source_acquisition import validate_private_bundle_document

EXTRACTOR_ID = "video-source-extraction-v2"
SANDBOX_PROFILE_ID = "video-source-extraction-sandbox-v2"
SCHEMA_VERSION = 1
SANDBOX_EXECUTABLE = "/usr/bin/sandbox-exec"
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_STDOUT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_EXTRACTED_BYTES = 8 * 1024 * 1024
MAX_UNITS_PER_SOURCE = 10_000
MAX_STDERR_BYTES = 64 * 1024
SUBPROCESS_TIMEOUT_SECONDS = 120.0
EXTRACTION_TOTAL_TIMEOUT_SECONDS = 600.0
MAX_TOOL_BYTES = 64 * 1024 * 1024
_CHUNK_SIZE = 64 * 1024
_SUPPORTED_FORMATS = frozenset({"pdf", "txt", "md", "doc", "docx", "rtf", "odt"})
_DETECTED_FORMATS = frozenset({"pdf", "text", "rtf", "office_zip", "ole"})
_PRIVATE_SOURCE_KINDS = frozenset(
    {"reserved_editorial", "catalog", "valueset", "live_census", "validated_usage", "oracle"}
)
_PUBLIC_KEYS = frozenset(
    {
        "schema_version",
        "operation",
        "status",
        "private_roster_complete",
        "sandbox_verified",
        "format_supported",
        "raw_payloads_present",
        "gaps",
        "error_codes",
    }
)
PUBLIC_RESULT_KEYS = _PUBLIC_KEYS
_ERROR_CODES = frozenset(
    {
        "BUNDLE_INVALID",
        "SOURCE_ROSTER_INVALID",
        "REGISTRY_INVALID",
        "ROOT_INVALID",
        "LOCATOR_INVALID",
        "SOURCE_INVALID",
        "SOURCE_DRIFT",
        "SOURCE_TOO_LARGE",
        "FORMAT_UNSUPPORTED",
        "FORMAT_MISMATCH",
        "TOOL_INVALID",
        "SANDBOX_UNAVAILABLE",
        "SANDBOX_CANARY_FAILED",
        "EXTRACTION_FAILED",
        "EXTRACTION_TIMEOUT",
        "EXTRACTION_OUTPUT_TOO_LARGE",
        "EXTRACTION_STDOUT_INVALID",
        "ENVELOPE_INVALID",
    }
)
ERROR_CODES = _ERROR_CODES
_READ_DENY_ROOTS = (
    str(Path.home()),
    "/Volumes",
    "/Network",
    "/private/var/root",
    "/Library/Keychains",
)
_CANARY_EXECUTABLES = ("/bin/cat", "/usr/bin/nc", "/usr/bin/touch", "/usr/bin/true")
PDF_EXECUTABLE = "/usr/bin/osascript"
_PDFKIT_JXA = (
    'ObjC.import("Foundation");ObjC.import("PDFKit");'
    "var d=$.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;"
    "var p=$.PDFDocument.alloc.initWithData(d);"
    'if(!p){throw new Error("invalid pdf");}'
    "var a=[];"
    "for(var i=0;i<p.pageCount;i++){var s=p.pageAtIndex(i).string;"
    'a.push({ordinal:i+1,text:s?ObjC.unwrap(s):""});}'
    'var o=JSON.stringify({schema_version:1,unit_kind:"page",units:a});'
    "var z=$(o).dataUsingEncoding($.NSUTF8StringEncoding);"
    "$.NSFileHandle.fileHandleWithStandardOutput.writeData(z);"
)


class VideoSourceExtractionError(RuntimeError):
    """A path- and payload-free extraction failure."""

    def __init__(self, code: str = "EXTRACTION_FAILED") -> None:
        self.code = code if code in _ERROR_CODES else "EXTRACTION_FAILED"
        super().__init__("video source extraction blocked")


@dataclass(frozen=True)
class SourceExtractionOutcome:
    """The private self-hashed envelope and its public-safe receipt."""

    private_envelope: Mapping[str, Any]
    public_result: Mapping[str, Any]


@dataclass(frozen=True)
class _ToolCapability:
    executable: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    content_sha256: str

    @property
    def identity_sha256(self) -> str:
        return _sha256_bytes(
            _canonical_json(
                {
                    "executable": self.executable,
                    "device": self.device,
                    "inode": self.inode,
                    "size": self.size,
                    "mtime_ns": self.mtime_ns,
                    "ctime_ns": self.ctime_ns,
                    "content_sha256": self.content_sha256,
                }
            )
        )


Runner = Callable[
    [Sequence[str], Mapping[str, str], float, int | None],
    subprocess.CompletedProcess[bytes],
]


def _blocked(code: str) -> None:
    raise VideoSourceExtractionError(code)


def _public_result(
    *,
    valid: bool,
    roster_complete: bool,
    sandbox_verified: bool,
    format_supported: bool,
    errors: Sequence[str] = (),
    gaps: int | None = None,
) -> dict[str, Any]:
    codes = sorted(set(errors))
    if not set(codes) <= _ERROR_CODES:
        raise AssertionError("unknown extraction error code")
    result = {
        "schema_version": SCHEMA_VERSION,
        "operation": "extract-sources",
        "status": "VALID" if valid and sandbox_verified else "SYNTHETIC" if valid else "INVALID",
        "private_roster_complete": roster_complete,
        "sandbox_verified": sandbox_verified,
        "format_supported": format_supported,
        "raw_payloads_present": False,
        "gaps": (0 if valid else max(1, len(codes))) if gaps is None else max(0, gaps),
        "error_codes": codes,
    }
    if set(result) != _PUBLIC_KEYS:
        raise AssertionError("public extraction result is not allowlisted")
    return result


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError, UnicodeError):
        _blocked("ENVELOPE_INVALID")


def _safe_parts(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\x00" in value:
        _blocked("LOCATOR_INVALID")
    if os.path.isabs(value) or "\\" in value:
        _blocked("LOCATOR_INVALID")
    parts = tuple(value.split("/"))
    if not parts or any(not part or part in {".", ".."} for part in parts):
        _blocked("LOCATOR_INVALID")
    return parts


def _assert_directory(info: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != _current_uid()
    ):
        _blocked("ROOT_INVALID")


def _open_directory(path: Path) -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    if nofollow is None or directory is None:
        _blocked("ROOT_INVALID")
    try:
        before = path.lstat()
        _assert_directory(before)
        descriptor = os.open(path, os.O_RDONLY | directory | nofollow | close_on_exec)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            os.close(descriptor)
            _blocked("ROOT_INVALID")
        return descriptor
    except VideoSourceExtractionError:
        raise
    except OSError:
        _blocked("ROOT_INVALID")


def _open_child_directory(parent: int, name: str) -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    if nofollow is None or directory is None:
        _blocked("ROOT_INVALID")
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | directory | nofollow | close_on_exec,
            dir_fd=parent,
        )
        entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(entry.st_mode)
            or stat.S_ISLNK(entry.st_mode)
            or entry.st_uid != _current_uid()
            or (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            os.close(descriptor)
            _blocked("ROOT_INVALID")
        return descriptor
    except VideoSourceExtractionError:
        raise
    except OSError:
        _blocked("ROOT_INVALID")


def _assert_source_file(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_uid != _current_uid() or info.st_nlink != 1:
        _blocked("SOURCE_INVALID")
    if info.st_size > MAX_SOURCE_BYTES:
        _blocked("SOURCE_TOO_LARGE")


def _assert_path_matches_fd(path: Path, descriptor: int) -> os.stat_result:
    try:
        entry = path.lstat()
        opened = os.fstat(descriptor)
    except OSError:
        _blocked("SOURCE_DRIFT")
    _assert_source_file(entry)
    _assert_source_file(opened)
    if (
        (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino)
        or entry.st_size != opened.st_size
        or entry.st_mtime_ns != opened.st_mtime_ns
        or entry.st_ctime_ns != opened.st_ctime_ns
    ):
        _blocked("SOURCE_DRIFT")
    return opened


def _close(descriptor: int | None) -> None:
    if descriptor is not None:
        with suppress(OSError):
            os.close(descriptor)


def _bundle_entries(
    bundle: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Path, tuple[Mapping[str, Any], ...]]:
    try:
        if not isinstance(bundle, Mapping) or not validate_private_bundle_document(bundle):
            _blocked("BUNDLE_INVALID")
        manifest = bundle["manifest"]
        registry = bundle["locator_registry"]
        entries = registry["entries"]
        root_value = registry["root_locator"]
        if not isinstance(manifest, Mapping) or not isinstance(registry, Mapping):
            _blocked("BUNDLE_INVALID")
        if not isinstance(root_value, str) or not os.path.isabs(root_value):
            _blocked("REGISTRY_INVALID")
        if not isinstance(entries, list) or not entries:
            _blocked("REGISTRY_INVALID")
        sources = {item["source_id"]: item for item in manifest["sources"]}
        if len(sources) != len(manifest["sources"]):
            _blocked("SOURCE_ROSTER_INVALID")
        if any(
            source["kind"] not in _PRIVATE_SOURCE_KINDS
            or source["identity_storage"] != "local-confidential-receipt"
            or source["sensitivity"] not in {"internal_editorial", "internal_aggregate"}
            for source in sources.values()
        ):
            _blocked("SOURCE_ROSTER_INVALID")
        normalized: list[Mapping[str, Any]] = []
        seen: set[str] = set()
        for entry in sorted(
            entries, key=lambda item: (str(item.get("source_id")), str(item.get("locator")))
        ):
            if not isinstance(entry, Mapping) or entry.get("source_id") not in sources:
                _blocked("REGISTRY_INVALID")
            source_id = entry["source_id"]
            if source_id in seen:
                _blocked("REGISTRY_INVALID")
            seen.add(source_id)
            _safe_parts(entry.get("locator"))
            if entry.get("format") not in _SUPPORTED_FORMATS:
                _blocked("FORMAT_UNSUPPORTED")
            normalized.append(entry)
        if seen != set(sources):
            _blocked("REGISTRY_INVALID")
        try:
            root = Path(root_value).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            _blocked("ROOT_INVALID")
        if not root.is_absolute() or root_value != str(root):
            _blocked("ROOT_INVALID")
        return manifest, root, tuple(normalized)
    except VideoSourceExtractionError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError):
        _blocked("BUNDLE_INVALID")


def _open_source(root: Path, locator: str) -> tuple[int, Path]:
    parts = _safe_parts(locator)
    root_fd: int | None = None
    parent: int | None = None
    descriptor: int | None = None
    try:
        root_fd = _open_directory(root)
        parent = root_fd
        for name in parts[:-1]:
            child = _open_child_directory(parent, name)
            if parent != root_fd:
                _close(parent)
            parent = child
        name = parts[-1]
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            _blocked("SOURCE_INVALID")
        entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
        _assert_source_file(entry)
        descriptor = os.open(
            name, os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0), dir_fd=parent
        )
        _assert_path_matches_fd(root.joinpath(*parts), descriptor)
        return descriptor, root.joinpath(*parts)
    except VideoSourceExtractionError:
        _close(descriptor)
        raise
    except OSError:
        _close(descriptor)
        _blocked("SOURCE_INVALID")
    finally:
        _close(parent if parent != root_fd else None)
        _close(root_fd)


def _hash_fd(descriptor: int) -> tuple[str, os.stat_result]:
    try:
        before = os.fstat(descriptor)
        _assert_source_file(before)
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, _CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SOURCE_BYTES:
                _blocked("SOURCE_TOO_LARGE")
            digest.update(chunk)
        after = os.fstat(descriptor)
        _assert_source_file(after)
        if (
            (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or total != after.st_size
        ):
            _blocked("SOURCE_DRIFT")
        return "sha256:" + digest.hexdigest(), after
    except VideoSourceExtractionError:
        raise
    except OSError:
        _blocked("SOURCE_INVALID")


def _detected_format(descriptor: int) -> str:
    """Detect the parser family from bounded content, never from a filename."""

    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        prefix = os.read(descriptor, 8192)
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError:
        _blocked("SOURCE_INVALID")
    if prefix.startswith(b"%PDF-"):
        return "pdf"
    if prefix.startswith(b"PK\x03\x04"):
        return "office_zip"
    if prefix.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"
    if prefix.lstrip().startswith(b"{\\rtf"):
        return "rtf"
    if b"\x00" not in prefix:
        try:
            prefix.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            return "text"
    _blocked("FORMAT_UNSUPPORTED")


def _assert_declared_format(declared: str, detected: str) -> None:
    expected = {
        "pdf": "pdf",
        "txt": "text",
        "md": "text",
        "rtf": "rtf",
        "doc": "ole",
        "docx": "office_zip",
        "odt": "office_zip",
    }.get(declared)
    if expected != detected:
        _blocked("FORMAT_MISMATCH")


def _sandbox_profile(command: Sequence[str]) -> str:
    def quote(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    requested_exec = (*_CANARY_EXECUTABLES, command[0])
    allowed_exec = tuple(
        dict.fromkeys(path for item in requested_exec for path in (item, os.path.realpath(item)))
    )
    clauses = [
        "(version 1)",
        "(deny default)",
        "(allow process-fork)",
        "(allow sysctl-read)",
        "(allow file-read*)",
        "(deny network*)",
        "(deny file-write*)",
    ]
    clauses.extend(f'(allow process-exec (literal "{quote(path)}"))' for path in allowed_exec)
    clauses.extend(f'(deny file-read* (subpath "{quote(path)}"))' for path in _READ_DENY_ROOTS)
    return "".join(clauses)


def _existing_denied_read_canary() -> Path:
    candidate = Path.home() / ".gitconfig"
    if candidate.is_file():
        return candidate
    return Path(__file__).resolve()


def _run_subprocess(
    argv: Sequence[str],
    env: Mapping[str, str],
    timeout: float,
    stdin_fd: int | None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        process = subprocess.Popen(
            list(argv),
            stdin=stdin_fd if stdin_fd is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(env),
            cwd="/",
            shell=False,
        )
    except (OSError, ValueError):
        _blocked("SANDBOX_UNAVAILABLE")
    assert process.stdout is not None and process.stderr is not None
    stdout_fd, stderr_fd = process.stdout.fileno(), process.stderr.fileno()
    streams = {
        stdout_fd: (process.stdout, MAX_STDOUT_BYTES),
        stderr_fd: (process.stderr, MAX_STDERR_BYTES),
    }
    output: dict[int, bytearray] = {stdout_fd: bytearray(), stderr_fd: bytearray()}
    deadline = time.monotonic() + timeout
    try:
        while streams:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                _blocked("EXTRACTION_TIMEOUT")
            ready, _, _ = select.select(tuple(streams), (), (), min(remaining, 0.25))
            for fd in ready:
                stream, limit = streams[fd]
                chunk = os.read(fd, min(_CHUNK_SIZE, limit + 1 - len(output[fd])))
                if not chunk:
                    streams.pop(fd)
                    stream.close()
                    continue
                output[fd].extend(chunk)
                if len(output[fd]) > limit:
                    process.kill()
                    process.wait()
                    _blocked("EXTRACTION_OUTPUT_TOO_LARGE")
        return subprocess.CompletedProcess(
            list(argv), process.wait(timeout=1), bytes(output[stdout_fd]), bytes(output[stderr_fd])
        )
    except VideoSourceExtractionError:
        raise
    except (OSError, subprocess.TimeoutExpired):
        with suppress(OSError):
            process.kill()
        with suppress(OSError):
            process.wait()
        _blocked("EXTRACTION_FAILED")


def _invoke(
    command: Sequence[str],
    profile: str,
    runner: Runner | None,
    *,
    stdin_fd: int | None = None,
    deadline: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    if not os.path.isabs(SANDBOX_EXECUTABLE):
        _blocked("SANDBOX_UNAVAILABLE")
    timeout = SUBPROCESS_TIMEOUT_SECONDS
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
        if timeout <= 0:
            _blocked("EXTRACTION_TIMEOUT")
    argv = [SANDBOX_EXECUTABLE, "-p", profile, *command]
    if runner is not None:
        try:
            result = runner(
                argv,
                {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
                timeout,
                stdin_fd,
            )
        except Exception:
            _blocked("EXTRACTION_FAILED")
        if not isinstance(result, subprocess.CompletedProcess):
            _blocked("EXTRACTION_FAILED")
    else:
        result = _run_subprocess(
            argv,
            {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            timeout,
            stdin_fd,
        )
    if (
        not isinstance(result.stdout, bytes)
        or not isinstance(result.stderr, bytes)
        or len(result.stdout) > MAX_STDOUT_BYTES
        or len(result.stderr) > MAX_STDERR_BYTES
    ):
        _blocked("EXTRACTION_OUTPUT_TOO_LARGE")
    return result


def _tool_capability(path: str) -> _ToolCapability:
    descriptor: int | None = None
    try:
        requested = Path(path)
        if not requested.is_absolute():
            _blocked("TOOL_INVALID")
        resolved = requested.resolve(strict=True)
        before = resolved.lstat()
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or before.st_size < 1
            or before.st_size > MAX_TOOL_BYTES
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            _blocked("TOOL_INVALID")
        for directory in resolved.parents:
            ancestor = directory.lstat()
            if (
                stat.S_ISLNK(ancestor.st_mode)
                or not stat.S_ISDIR(ancestor.st_mode)
                or ancestor.st_uid != 0
                or stat.S_IMODE(ancestor.st_mode) & 0o022
            ):
                _blocked("TOOL_INVALID")
        descriptor = os.open(
            resolved,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        if (
            (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or before.st_size != opened.st_size
            or before.st_mtime_ns != opened.st_mtime_ns
            or before.st_ctime_ns != opened.st_ctime_ns
        ):
            _blocked("TOOL_INVALID")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, _CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_TOOL_BYTES:
                _blocked("TOOL_INVALID")
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino)
            or opened.st_size != after.st_size
            or opened.st_mtime_ns != after.st_mtime_ns
            or opened.st_ctime_ns != after.st_ctime_ns
            or total != after.st_size
        ):
            _blocked("TOOL_INVALID")
        return _ToolCapability(
            executable=str(resolved),
            device=after.st_dev,
            inode=after.st_ino,
            size=after.st_size,
            mtime_ns=after.st_mtime_ns,
            ctime_ns=after.st_ctime_ns,
            content_sha256="sha256:" + digest.hexdigest(),
        )
    except VideoSourceExtractionError:
        raise
    except (OSError, RuntimeError, ValueError):
        _blocked("TOOL_INVALID")
    finally:
        _close(descriptor)


def _validate_tool_capability(capability: _ToolCapability) -> None:
    if _tool_capability(capability.executable) != capability:
        _blocked("TOOL_INVALID")


def _format_command(detected_format: str) -> tuple[list[str], _ToolCapability]:
    if detected_format == "pdf":
        tool = _tool_capability(PDF_EXECUTABLE)
        return [tool.executable, "-l", "JavaScript", "-e", _PDFKIT_JXA], tool
    if detected_format == "text":
        tool = _tool_capability("/bin/cat")
        return [tool.executable], tool
    if detected_format in {"rtf", "office_zip", "ole"}:
        tool = _tool_capability("/usr/bin/textutil")
        return [tool.executable, "-convert", "txt", "-stdin", "-stdout"], tool
    _blocked("FORMAT_UNSUPPORTED")


def _decode_extracted_units(
    detected_format: str, payload: bytes
) -> tuple[str, list[dict[str, Any]], int]:
    """Turn parser output into deterministic opaque page/document units."""

    if detected_format == "pdf":
        try:
            decoded = payload.decode("utf-8")

            def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                value: dict[str, Any] = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError
                    value[key] = item
                return value

            document = json.loads(
                decoded,
                object_pairs_hook=unique_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        except (RecursionError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
            _blocked("EXTRACTION_STDOUT_INVALID")
        if (
            not isinstance(document, Mapping)
            or set(document) != {"schema_version", "unit_kind", "units"}
            or type(document["schema_version"]) is not int
            or document["schema_version"] != SCHEMA_VERSION
            or document["unit_kind"] != "page"
            or not isinstance(document["units"], list)
            or not 1 <= len(document["units"]) <= MAX_UNITS_PER_SOURCE
        ):
            _blocked("EXTRACTION_STDOUT_INVALID")
        parsed = document["units"]
        unit_kind = "page"
        prefix = "page"
    else:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            _blocked("EXTRACTION_STDOUT_INVALID")
        if not text.strip():
            _blocked("EXTRACTION_STDOUT_INVALID")
        parsed = [{"ordinal": 1, "text": text}]
        unit_kind = "document"
        prefix = "document"

    units: list[dict[str, Any]] = []
    total = 0
    has_text = False
    for ordinal, item in enumerate(parsed, start=1):
        if (
            not isinstance(item, Mapping)
            or set(item) != {"ordinal", "text"}
            or type(item["ordinal"]) is not int
            or item["ordinal"] != ordinal
            or not isinstance(item["text"], str)
        ):
            _blocked("EXTRACTION_STDOUT_INVALID")
        try:
            raw = item["text"].encode("utf-8")
        except UnicodeEncodeError:
            _blocked("EXTRACTION_STDOUT_INVALID")
        total += len(raw)
        if total > MAX_TOTAL_EXTRACTED_BYTES:
            _blocked("EXTRACTION_OUTPUT_TOO_LARGE")
        has_text = has_text or bool(item["text"].strip())
        units.append(
            {
                "source_locator": f"{prefix}-{ordinal:06d}",
                "ordinal": ordinal,
                "text_sha256": _sha256_bytes(raw),
                "text": item["text"],
            }
        )
    if not has_text:
        _blocked("EXTRACTION_STDOUT_INVALID")
    return unit_kind, units, total


def _runtime_identity_sha256() -> str:
    return _sha256_bytes(
        _canonical_json(
            {
                "python": sys.version.split()[0],
                "platform": sys.platform,
                "extractor_id": EXTRACTOR_ID,
                "sandbox_profile_id": SANDBOX_PROFILE_ID,
            }
        )
    )


def _extraction_input_sha(manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> str:
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "manifest_sha256": manifest_digest(manifest),
        "sources": [
            {
                "source_id": row["source_id"],
                "source_ref": row["source_ref"],
                "source_content_sha256": row["source_content_sha256"],
                "detected_format": row["detected_format"],
                "tool_identity_sha256": row["tool_identity_sha256"],
                "command_sha256": row["command_sha256"],
                "sandbox_profile_sha256": row["sandbox_profile_sha256"],
                "unit_roster_sha256": row["unit_roster_sha256"],
            }
            for row in rows
        ],
    }
    return _sha256_bytes(_canonical_json(evidence))


def _build_envelope(
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    evidence_mode: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "video-semantics/private-source-extraction-v1",
        "status": "VALID",
        "manifest_sha256": manifest_digest(manifest),
        "extraction_input_sha256": _extraction_input_sha(manifest, rows),
        "extractor_id": EXTRACTOR_ID,
        "sandbox_profile_id": SANDBOX_PROFILE_ID,
        "runtime_identity_sha256": _runtime_identity_sha256(),
        "evidence_mode": evidence_mode,
        "sources": [dict(row) for row in rows],
        "private_roster_complete": True,
        "gaps": 0,
    }
    body["envelope_sha256"] = _sha256_bytes(_canonical_json(body))
    if len(_canonical_json(body)) > MAX_PRIVATE_FILE_BYTES:
        _blocked("EXTRACTION_OUTPUT_TOO_LARGE")
    return body


def validate_private_envelope(
    envelope: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    require_real: bool = False,
    source_bundle: Mapping[str, Any] | None = None,
) -> None:
    try:
        if not isinstance(envelope, Mapping) or set(envelope) != {
            "schema_version",
            "artifact_kind",
            "status",
            "manifest_sha256",
            "extraction_input_sha256",
            "extractor_id",
            "sandbox_profile_id",
            "runtime_identity_sha256",
            "evidence_mode",
            "sources",
            "private_roster_complete",
            "gaps",
            "envelope_sha256",
        }:
            _blocked("ENVELOPE_INVALID")
        if (
            type(envelope["schema_version"]) is not int
            or envelope["schema_version"] != SCHEMA_VERSION
            or envelope["artifact_kind"] != "video-semantics/private-source-extraction-v1"
            or envelope["status"] != "VALID"
            or envelope["manifest_sha256"] != manifest_digest(manifest)
            or envelope["extractor_id"] != EXTRACTOR_ID
            or envelope["sandbox_profile_id"] != SANDBOX_PROFILE_ID
            or envelope["runtime_identity_sha256"] != _runtime_identity_sha256()
            or envelope["evidence_mode"] not in {"real", "synthetic"}
            or (require_real and envelope["evidence_mode"] != "real")
            or envelope["private_roster_complete"] is not True
            or type(envelope["gaps"]) is not int
            or envelope["gaps"] != 0
            or not isinstance(envelope["sources"], list)
        ):
            _blocked("ENVELOPE_INVALID")
        body = {key: value for key, value in envelope.items() if key != "envelope_sha256"}
        if envelope.get("envelope_sha256") != _sha256_bytes(_canonical_json(body)):
            _blocked("ENVELOPE_INVALID")
        source_by_id = {source["source_id"]: source for source in manifest["sources"]}
        if len(source_by_id) != len(manifest["sources"]):
            _blocked("ENVELOPE_INVALID")
        observed: set[str] = set()
        total = 0
        for row in envelope["sources"]:
            if not isinstance(row, Mapping) or set(row) != {
                "source_id",
                "source_ref",
                "source_content_sha256",
                "extractor_id",
                "detected_format",
                "tool_identity_sha256",
                "command_sha256",
                "sandbox_profile_sha256",
                "unit_kind",
                "unit_counts",
                "unit_roster_sha256",
                "units",
            }:
                _blocked("ENVELOPE_INVALID")
            source = source_by_id.get(row["source_id"])
            if (
                source is None
                or row["source_id"] in observed
                or row["source_ref"] != source["source_ref"]
                or row["source_content_sha256"] != source["content_sha256"]
                or row["extractor_id"] != EXTRACTOR_ID
                or row["detected_format"] not in _DETECTED_FORMATS
                or not isinstance(row["tool_identity_sha256"], str)
                or not row["tool_identity_sha256"].startswith("sha256:")
                or not isinstance(row["command_sha256"], str)
                or not row["command_sha256"].startswith("sha256:")
                or not isinstance(row["sandbox_profile_sha256"], str)
                or not row["sandbox_profile_sha256"].startswith("sha256:")
                or row["unit_kind"] != ("page" if row["detected_format"] == "pdf" else "document")
                or not isinstance(row["unit_counts"], Mapping)
                or set(row["unit_counts"])
                != {"items_in", "items_out", "items_distinct", "items_gaps"}
                or any(type(value) is not int for value in row["unit_counts"].values())
                or any(value < 0 for value in row["unit_counts"].values())
                or not isinstance(row["unit_roster_sha256"], str)
                or not row["unit_roster_sha256"].startswith("sha256:")
                or not isinstance(row["units"], list)
                or not 1 <= len(row["units"]) <= MAX_UNITS_PER_SOURCE
            ):
                _blocked("ENVELOPE_INVALID")
            command, tool = _format_command(row["detected_format"])
            expected_command_sha256 = _sha256_bytes(_canonical_json(command))
            expected_profile_sha256 = _sha256_bytes(_sandbox_profile(command).encode("utf-8"))
            if (
                row["tool_identity_sha256"] != tool.identity_sha256
                or row["command_sha256"] != expected_command_sha256
                or row["sandbox_profile_sha256"] != expected_profile_sha256
            ):
                _blocked("ENVELOPE_INVALID")
            prefix = "page" if row["unit_kind"] == "page" else "document"
            observed_locators: set[str] = set()
            for ordinal, unit in enumerate(row["units"], start=1):
                if (
                    not isinstance(unit, Mapping)
                    or set(unit) != {"source_locator", "ordinal", "text_sha256", "text"}
                    or type(unit["ordinal"]) is not int
                    or unit["ordinal"] != ordinal
                    or unit["source_locator"] != f"{prefix}-{ordinal:06d}"
                    or unit["source_locator"] in observed_locators
                    or not isinstance(unit["text"], str)
                ):
                    _blocked("ENVELOPE_INVALID")
                try:
                    raw = unit["text"].encode("utf-8")
                except UnicodeEncodeError:
                    _blocked("ENVELOPE_INVALID")
                total += len(raw)
                if total > MAX_TOTAL_EXTRACTED_BYTES or unit["text_sha256"] != _sha256_bytes(raw):
                    _blocked("ENVELOPE_INVALID")
                observed_locators.add(unit["source_locator"])
            expected_count = len(row["units"])
            if row["unit_counts"] != {
                "items_in": expected_count,
                "items_out": expected_count,
                "items_distinct": expected_count,
                "items_gaps": 0,
            } or row["unit_roster_sha256"] != _sha256_bytes(_canonical_json(row["units"])):
                _blocked("ENVELOPE_INVALID")
            observed.add(row["source_id"])
        if observed != set(source_by_id):
            _blocked("ENVELOPE_INVALID")
        if envelope["extraction_input_sha256"] != _extraction_input_sha(
            manifest, envelope["sources"]
        ):
            _blocked("ENVELOPE_INVALID")
        if len(_canonical_json(envelope)) > MAX_PRIVATE_FILE_BYTES:
            _blocked("ENVELOPE_INVALID")
        if require_real:
            if source_bundle is None:
                _blocked("ENVELOPE_INVALID")
            source_manifest, _, _ = _bundle_entries(source_bundle)
            if _canonical_json(source_manifest) != _canonical_json(manifest):
                _blocked("ENVELOPE_INVALID")
            independently_recomputed = extract_private_source(source_bundle)
            if (
                independently_recomputed.public_result.get("status") != "VALID"
                or independently_recomputed.public_result.get("sandbox_verified") is not True
                or _canonical_json(independently_recomputed.private_envelope)
                != _canonical_json(envelope)
            ):
                _blocked("ENVELOPE_INVALID")
    except VideoSourceExtractionError:
        raise
    except (AttributeError, KeyError, RecursionError, TypeError, UnicodeError, ValueError):
        _blocked("ENVELOPE_INVALID")


def verify_sandbox_boundary(
    profile: str,
    *,
    runner: Runner | None = None,
    deadline: float | None = None,
) -> None:
    """Prove allowed stdin plus denied home read, write and numeric network."""

    if not Path(SANDBOX_EXECUTABLE).is_file():
        _blocked("SANDBOX_UNAVAILABLE")
    denied_read = _existing_denied_read_canary().resolve(strict=True)
    denied_roots = tuple(Path(path).resolve(strict=False) for path in _READ_DENY_ROOTS)
    if not any(denied_read == root or root in denied_read.parents for root in denied_roots):
        _blocked("SANDBOX_CANARY_FAILED")
    with tempfile.TemporaryFile(prefix="metis-video-canary-") as allowed_input:
        allowed_input.write(b"synthetic-sandbox-canary")
        allowed_input.flush()
        allowed_input.seek(0)
        allowed = _invoke(
            ["/bin/cat"],
            profile,
            runner,
            stdin_fd=allowed_input.fileno(),
            deadline=deadline,
        )
        if allowed.returncode != 0 or allowed.stdout != b"synthetic-sandbox-canary":
            _blocked("SANDBOX_CANARY_FAILED")
    denied = _invoke(["/bin/cat", str(denied_read)], profile, runner, deadline=deadline)
    if denied.returncode == 0 or denied.stdout:
        _blocked("SANDBOX_CANARY_FAILED")
    with tempfile.TemporaryDirectory(prefix="metis-video-write-canary-") as temp:
        write_target = Path(temp) / ("blocked-" + secrets.token_hex(8))
        denied_write = _invoke(
            ["/usr/bin/touch", str(write_target)],
            profile,
            runner,
            deadline=deadline,
        )
        if denied_write.returncode == 0 or denied_write.stdout or write_target.exists():
            _blocked("SANDBOX_CANARY_FAILED")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        denied_network = _invoke(
            ["/usr/bin/nc", "-z", "-w", "1", "127.0.0.1", str(port)],
            profile,
            runner,
            deadline=deadline,
        )
        if denied_network.returncode == 0 or denied_network.stdout:
            _blocked("SANDBOX_CANARY_FAILED")
    finally:
        listener.close()


def extract_private_source(
    bundle: Mapping[str, Any], *, runner: Runner | None = None
) -> SourceExtractionOutcome:
    """Extract every registry source in deterministic order into one envelope."""

    manifest, root, entries = _bundle_entries(bundle)
    root_fd = _open_directory(root)
    _close(root_fd)
    rows: list[Mapping[str, Any]] = []
    source_by_id = {item["source_id"]: item for item in manifest["sources"]}
    total_extracted = 0
    deadline = time.monotonic() + EXTRACTION_TOTAL_TIMEOUT_SECONDS
    for entry in entries:
        if time.monotonic() >= deadline:
            _blocked("EXTRACTION_TIMEOUT")
        source = source_by_id[entry["source_id"]]
        descriptor: int | None = None
        try:
            descriptor, source_path = _open_source(root, entry["locator"])
            source_hash_before, metadata_before = _hash_fd(descriptor)
            _assert_path_matches_fd(source_path, descriptor)
            if (
                source_hash_before != source["content_sha256"]
                or entry["size_bytes"] != metadata_before.st_size
            ):
                _blocked("SOURCE_DRIFT")
            detected_format = _detected_format(descriptor)
            _assert_declared_format(entry["format"], detected_format)
            command, tool = _format_command(detected_format)
            _validate_tool_capability(tool)
            command_sha256 = _sha256_bytes(_canonical_json(command))
            profile = _sandbox_profile(command)
            profile_sha256 = _sha256_bytes(profile.encode("utf-8"))
            verify_sandbox_boundary(profile, runner=runner, deadline=deadline)
            if time.monotonic() >= deadline:
                _blocked("EXTRACTION_TIMEOUT")
            os.lseek(descriptor, 0, os.SEEK_SET)
            result = _invoke(
                command,
                profile,
                runner,
                stdin_fd=descriptor,
                deadline=deadline,
            )
            if result.returncode != 0:
                _blocked("EXTRACTION_FAILED")
            unit_kind, units, extracted_bytes = _decode_extracted_units(
                detected_format, result.stdout
            )
            total_extracted += extracted_bytes
            if total_extracted > MAX_TOTAL_EXTRACTED_BYTES:
                _blocked("EXTRACTION_OUTPUT_TOO_LARGE")
            source_hash_after, metadata_after = _hash_fd(descriptor)
            _assert_path_matches_fd(source_path, descriptor)
            if (
                source_hash_after != source_hash_before
                or metadata_before.st_mtime_ns != metadata_after.st_mtime_ns
                or metadata_before.st_ctime_ns != metadata_after.st_ctime_ns
            ):
                _blocked("SOURCE_DRIFT")
            _validate_tool_capability(tool)
            rows.append(
                {
                    "source_id": source["source_id"],
                    "source_ref": source["source_ref"],
                    "source_content_sha256": source_hash_after,
                    "extractor_id": EXTRACTOR_ID,
                    "detected_format": detected_format,
                    "tool_identity_sha256": tool.identity_sha256,
                    "command_sha256": command_sha256,
                    "sandbox_profile_sha256": profile_sha256,
                    "unit_kind": unit_kind,
                    "unit_counts": {
                        "items_in": len(units),
                        "items_out": len(units),
                        "items_distinct": len(units),
                        "items_gaps": 0,
                    },
                    "unit_roster_sha256": _sha256_bytes(_canonical_json(units)),
                    "units": units,
                }
            )
        except VideoSourceExtractionError:
            raise
        except (KeyError, TypeError, OSError, UnicodeError, ValueError):
            _blocked("EXTRACTION_FAILED")
        finally:
            _close(descriptor)
    envelope = _build_envelope(
        manifest,
        rows,
        evidence_mode="real" if runner is None else "synthetic",
    )
    validate_private_envelope(envelope, manifest)
    return SourceExtractionOutcome(
        private_envelope=envelope,
        public_result=_public_result(
            valid=True,
            roster_complete=True,
            sandbox_verified=runner is None,
            format_supported=True,
            gaps=0,
        ),
    )


def public_failure(error: VideoSourceExtractionError) -> Mapping[str, Any]:
    """Return the finite public-safe representation of an extraction failure."""

    return _public_result(
        valid=False,
        roster_complete=False,
        sandbox_verified=False,
        format_supported=error.code not in {"FORMAT_UNSUPPORTED", "FORMAT_MISMATCH"},
        errors=(error.code,),
        gaps=1,
    )


def private_unit_roster(envelope: Mapping[str, Any]) -> Mapping[str, tuple[str, ...]]:
    """Derive the private source-ref/unit-locator roster after envelope validation."""

    try:
        return {
            row["source_ref"]: tuple(unit["source_locator"] for unit in row["units"])
            for row in envelope["sources"]
        }
    except (KeyError, TypeError):
        _blocked("ENVELOPE_INVALID")


__all__ = [
    "EXTRACTOR_ID",
    "ERROR_CODES",
    "MAX_SOURCE_BYTES",
    "MAX_STDERR_BYTES",
    "MAX_STDOUT_BYTES",
    "PUBLIC_RESULT_KEYS",
    "SourceExtractionOutcome",
    "SUBPROCESS_TIMEOUT_SECONDS",
    "VideoSourceExtractionError",
    "extract_private_source",
    "private_unit_roster",
    "public_failure",
    "validate_private_envelope",
    "verify_sandbox_boundary",
]
