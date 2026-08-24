"""Deterministic, payload-only materializer for the W3 Phase-B bundle.

The functions in this module census and copy already-local public inputs.  They
never install files, change host identities or services, read credentials, or
execute Node/Metis/model code.  Every source read is no-follow and is measured
before it can be admitted to a frozen roster.
"""

from __future__ import annotations

import base64
import csv
import ctypes
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from runtime import w3_broker_installer as installer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CPYTHON_ROOT = Path(
    "/Users/tommasotessarolo/.local/share/uv/python/cpython-3.13.3-macos-aarch64-none"
)
DEFAULT_METIS_ROOT = Path("/Users/tommasotessarolo/Developer/ares-matioska/metis")
DEFAULT_CAPSULE_EVIDENCE = PROJECT_ROOT / "manifests/w3-native-loader-evidence.json"
DEFAULT_NODE_PATH = Path("/Users/tommasotessarolo/.hermes/node/bin/node")
DEFAULT_WHEEL_ROOT = Path(installer.BOOTSTRAP_SOURCE_ROOT) / "wheels"
DEFAULT_CANDIDATES_PATH = PROJECT_ROOT / "manifests/w3-f1-f3-smoke-candidates.json"
DEFAULT_STAGE0_BUILD_A = Path("/private/var/tmp/w3-prod-build-a.Eov6hC/w3-installer-bootstrap")
DEFAULT_STAGE0_BUILD_B = Path("/private/var/tmp/w3-prod-build-b.3ddfD0/w3-installer-bootstrap")
DEFAULT_SEMANTIC_REGISTRY_PATH = PROJECT_ROOT / "manifests/w3-f1-f3-smoke-semantic-specs.json"
DEFAULT_SOURCE_ROOT = Path(installer.BOOTSTRAP_SOURCE_ROOT)
DEFAULT_BOOTSTRAP_SOURCE = Path(installer.BOOTSTRAP_BINARY_SOURCE_PATH)
DEFAULT_MANIFEST_ROOT = PROJECT_ROOT / "manifests"

_MANIFEST_OUTPUT_NAMES: Mapping[str, str] = {
    "manifest_payload": "w3-phase-b-install-bundle.json",
    "plan_payload": "w3-phase-b-install-plan.json",
    "descriptor_payload": "w3-phase-b-bootstrap.descriptor",
    "admin_invocation_payload": "w3-phase-b-admin-invocation.json",
}
_SOURCE_PUBLICATION_CHILDREN = ("artifacts", "install-root", "source-census", "metadata")

_SHA256_PREFIX = "sha256:"
_READ_CHUNK = 1024 * 1024
_ZIP_MAX_MEMBERS = 16_384
_ZIP_MAX_MEMBER_BYTES = 256 * 1024 * 1024
_ZIP_MAX_TOTAL_BYTES = 1024 * 1024 * 1024
_METIS_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
_METIS_TREE = "75473e26deff4084a0eb077a4c3e27d52dc07998"
_CANDIDATE_MANIFEST_SHA256 = (
    "sha256:4ee3e735179194b838ec38b0c11f1f9a166d640fcfece1eee68b6f9b6dd63bc5"
)
_SEMANTIC_REGISTRY_SHA256 = (
    "sha256:9b9aa14836eb6924e61df0ab1e0a7b7224f9958b78056ae66fd27f59868cc7c3"
)
_FIXTURE_ROLE_FIELDS = (
    ("F-1", "author", "target_source"),
    ("F-2", "before", "before_source"),
    ("F-2", "after", "after_source"),
    ("F-3", "mutated", "mutated_source"),
    ("F-3", "fixed", "fixed_source"),
)
_RUNTIME_EXPECTATIONS: Mapping[str, object] = {
    "node": "v22.22.3",
    "node_path": "node://v22.22.3",
    "loader_path": f"snapshot://{_METIS_REVISION}/{_METIS_TREE}/.metis-oracle/native_ts_loader.mjs",
    "loader_sha256": ("sha256:45e3557ce7ee345e2bca7de603c2ef8bc21aa2adb3f305d3f1cf6ee445273fee"),
    "loader_flags": ["--disable-warning=ExperimentalWarning", "--experimental-loader"],
    "runner_path": f"snapshot://{_METIS_REVISION}/{_METIS_TREE}/.metis-oracle/runner.ts",
    "snapshot_revision": _METIS_REVISION,
    "snapshot_tree": _METIS_TREE,
    "tooling_package_sha256": (
        "sha256:f8130a67f948720b339695fae614f32185610f762d69b85ff600f08971f2fb80"
    ),
    "tooling_lock_sha256": (
        "sha256:fed109b62f300ed824201f4b167d700072008b0b4a817cbb512a2eee32edc9fb"
    ),
    "node_modules_sha256": (
        "sha256:1cea5f2f0371d3c57b9ef9787707bc1079f88dc697c7be2c6c247e4018f6e463"
    ),
    "node_binary_sha256": installer.NODE_SHA256,
    "sandbox_exec_path": "sandbox-exec:///usr/bin/sandbox-exec",
    "oracle_policy_version": "2",
    "oracle_policy_sha256": (
        "sha256:deb8f45c9dfc2f336dbfb6f69a13e599a51929864ede8229969fa7f6e03f40aa"
    ),
    "execution_policy_sha256": (
        "sha256:4f29bf5e092d83993f19ad3d257cafd968a69b708679cecf5edc03cdf018de51"
    ),
}
_WHEEL_SPECS: Mapping[str, Mapping[str, object]] = {
    "cryptography": {
        "filename": "cryptography-47.0.0.whl",
        "size": 7_912_214,
        "sha256": ("sha256:160ad728f128972d362e714054f6ba0067cab7fb350c5202a9ae8ae4ce3ef1a0"),
        "dist_info": "cryptography-47.0.0.dist-info",
    },
    "cffi": {
        "filename": "cffi-2.0.0.whl",
        "size": 181_043,
        "sha256": ("sha256:45d5e886156860dc35862657e1494b9bae8dfa63bf56796f2fb56e1679fc0bca"),
        "dist_info": "cffi-2.0.0.dist-info",
    },
    "pycparser": {
        "filename": "pycparser-3.0.whl",
        "size": 48_172,
        "sha256": ("sha256:b727414169a36b7d524c1c3e31839a521725078d7b2ff038656844266160a992"),
        "dist_info": "pycparser-3.0.dist-info",
    },
}
_PROJECT_SOURCE_PATHS: Mapping[str, Path] = {
    f"{installer.PYTHON_SITE_PACKAGES}/runtime/{name}": PROJECT_ROOT / "runtime" / name
    for name in (
        "w3_broker_service.py",
        "w3_anchor_service.py",
        "w3_broker_protocol.py",
        "w3_ed25519.py",
        "w3_protected_broker.py",
        "w3_installed_worker.py",
        "w3_broker_installer.py",
        "w3_broker_executor.py",
        "w3_phase_b_evidence.py",
    )
} | {
    f"{installer.PYTHON_SITE_PACKAGES}/metis_model1/{name}": (
        PROJECT_ROOT / "src" / "metis_model1" / name
    )
    for name in ("__init__.py", "w3_broker_client.py", "provenance.py")
}


class MaterializerError(ValueError):
    """Fail-closed input or construction refusal."""


def _sha256(payload: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(payload).hexdigest()


def _safe_relative_path(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise MaterializerError(f"{label} path invalid")
    if unicodedata.normalize("NFC", value) != value:
        raise MaterializerError(f"{label} path is not NFC")
    raw_parts = value.split("/")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in raw_parts):
        raise MaterializerError(f"{label} path invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or tuple(path.parts) != tuple(raw_parts):
        raise MaterializerError(f"{label} path invalid")
    if any(len(part.encode("utf-8")) > 255 for part in path.parts):
        raise MaterializerError(f"{label} path component too long")
    return path.as_posix()


def _validate_path_tree(paths: Sequence[tuple[str, bool]], *, label: str) -> None:
    """Reject file/ancestor and case-insensitive component alias collisions."""

    nodes: dict[str, tuple[str, str]] = {}
    for raw_path, is_directory in paths:
        path = _safe_relative_path(raw_path, label=label)
        parts = path.split("/")
        for index in range(1, len(parts) + 1):
            spelling = "/".join(parts[:index])
            key = unicodedata.normalize("NFC", spelling).casefold()
            kind = "directory" if index < len(parts) or is_directory else "file"
            previous = nodes.get(key)
            if previous is not None and previous != (spelling, kind):
                raise MaterializerError(f"{label} path-tree collision")
            nodes[key] = (spelling, kind)


def validate_global_install_paths(entries: Sequence[Mapping[str, object]]) -> None:
    """Apply the path-tree collision policy across all install partitions."""

    paths: list[tuple[str, bool]] = []
    for item in entries:
        path = item.get("path") if isinstance(item, Mapping) else None
        if not isinstance(path, str) or not path.startswith("/"):
            raise MaterializerError("global install path invalid")
        paths.append((path[1:], False))
    _validate_path_tree(paths, label="global install")


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_mode,
        info.st_nlink,
    )


def _validate_absolute_ancestry(path: Path, *, expect_directory: bool) -> os.stat_result:
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts[1:]):
        raise MaterializerError("source path is not absolute and normalized")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, component in enumerate(path.parts[1:]):
            last = index == len(path.parts[1:]) - 1
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if not last or expect_directory:
                flags |= os.O_DIRECTORY
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        expected = stat.S_ISDIR(info.st_mode) if expect_directory else stat.S_ISREG(info.st_mode)
        if not expected:
            raise MaterializerError("source path type invalid")
        return info
    except OSError as error:
        raise MaterializerError("source path has unavailable or symlinked ancestry") from error
    finally:
        os.close(descriptor)


def _read_regular(
    path: Path,
    *,
    label: str,
    required_mode: int | None = None,
    expected_stat: os.stat_result | None = None,
) -> bytes:
    """Read a single-link regular leaf without following it or accepting a race."""

    ancestry = _validate_absolute_ancestry(path, expect_directory=False)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise MaterializerError(f"{label} unavailable") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise MaterializerError(f"{label} is not a single-link regular file")
        if _identity(ancestry) != _identity(before) or (
            expected_stat is not None and _identity(expected_stat) != _identity(before)
        ):
            raise MaterializerError(f"{label} identity changed before read")
        if required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode:
            raise MaterializerError(f"{label} mode invalid")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, _READ_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > before.st_size:
                raise MaterializerError(f"{label} grew while read")
        after = os.fstat(descriptor)
        payload = b"".join(chunks)
        if _identity(before) != _identity(after) or len(payload) != before.st_size:
            raise MaterializerError(f"{label} changed while read")
        try:
            named = os.stat(path, follow_symlinks=False)
        except OSError as error:
            raise MaterializerError(f"{label} identity disappeared") from error
        if _identity(named) != _identity(before):
            raise MaterializerError(f"{label} pathname changed while read")
        return payload
    finally:
        os.close(descriptor)


def is_forbidden_cpython_path(path: str) -> bool:
    """Return whether a CPython closure row could inject startup/import state."""

    normalized = path.replace("\\", "/").lower()
    basename = normalized.rsplit("/", 1)[-1]
    return (
        basename in {"sitecustomize.py", "usercustomize.py"}
        or basename.endswith((".pyc", ".pth", ".egg-link"))
        or "__pycache__" in PurePosixPath(normalized).parts
    )


def _walk_regular_files(root: Path) -> list[tuple[str, Path, os.stat_result]]:
    try:
        root_info = _validate_absolute_ancestry(root, expect_directory=True)
    except MaterializerError as error:
        raise MaterializerError("source root has unavailable or symlinked ancestry") from error
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise MaterializerError("source root is not a no-follow directory")

    rows: list[tuple[str, Path, os.stat_result]] = []
    stack: list[tuple[Path, PurePosixPath]] = [(root, PurePosixPath("."))]
    while stack:
        directory, relative_parent = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.encode("utf-8"))
        except OSError as error:
            raise MaterializerError("source directory unavailable") from error
        children: list[tuple[Path, PurePosixPath]] = []
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise MaterializerError("source entry unavailable") from error
            relative = relative_parent / entry.name
            relative_text = _safe_relative_path(relative.as_posix(), label="source")
            if stat.S_ISLNK(info.st_mode):
                continue
            if stat.S_ISDIR(info.st_mode):
                children.append((Path(entry.path), relative))
                continue
            if not stat.S_ISREG(info.st_mode):
                raise MaterializerError(f"source entry is non-regular: {relative_text}")
            rows.append((relative_text, Path(entry.path), info))
        stack.extend(reversed(children))
    rows.sort(key=lambda item: item[0].encode("utf-8"))
    return rows


def census_cpython(
    root: Path = DEFAULT_CPYTHON_ROOT,
    *,
    enforce_pin: bool = True,
) -> dict[str, object]:
    """Census the exact symlink-free CPython source closure.

    Raw source permissions are retained in the census.  Installation-mode
    normalization is a separate projection so the source truth is not hidden.
    """

    root = Path(root)
    rows: list[dict[str, object]] = []
    for relative, path, observed in _walk_regular_files(root):
        if is_forbidden_cpython_path(relative):
            continue
        raw = _read_regular(
            path,
            label=f"CPython source {relative}",
            expected_stat=observed,
        )
        mode = stat.S_IMODE(observed.st_mode)
        if mode not in {0o644, 0o755}:
            raise MaterializerError(f"CPython source mode invalid: {relative}")
        rows.append(
            {
                "path": relative,
                "size": len(raw),
                "sha256": _sha256(raw),
                "mode": mode,
            }
        )
    rows.sort(key=lambda row: str(row["path"]).encode("utf-8"))
    roster = {
        "files": len(rows),
        "bytes": sum(int(row["size"]) for row in rows),
        "sha256": installer._roster_hash(rows),
        "entries": rows,
    }
    if enforce_pin and (
        roster["files"] != installer.PYTHON_SOURCE_FILES
        or roster["bytes"] != installer.PYTHON_SOURCE_BYTES
        or roster["sha256"] != installer.PYTHON_SOURCE_ROSTER_SHA256
    ):
        raise MaterializerError("CPython source closure drifted from the release pin")
    return roster


def project_cpython_install(
    entries: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Project a raw CPython census into immutable installed file rows."""

    install_rows: list[dict[str, object]] = []
    source_map: list[dict[str, str]] = []
    seen: set[str] = set()
    collision_keys: set[str] = set()
    for item in entries:
        if not isinstance(item, Mapping) or set(item) != {"path", "size", "sha256", "mode"}:
            raise MaterializerError("CPython census row invalid")
        source_path = _safe_relative_path(str(item["path"]), label="CPython")
        if source_path in seen or is_forbidden_cpython_path(source_path):
            raise MaterializerError("CPython census path duplicated or forbidden")
        seen.add(source_path)
        collision_key = unicodedata.normalize("NFC", source_path).casefold()
        if collision_key in collision_keys:
            raise MaterializerError("CPython install path collision")
        collision_keys.add(collision_key)
        size = item["size"]
        digest = item["sha256"]
        mode = item["mode"]
        if (
            type(size) is not int
            or int(size) < 0
            or not isinstance(digest, str)
            or len(digest) != 71
            or not digest.startswith(_SHA256_PREFIX)
            or any(character not in "0123456789abcdef" for character in digest[7:])
            or type(mode) is not int
            or int(mode) not in {0o644, 0o755}
        ):
            raise MaterializerError("CPython census measurement invalid")
        install_path = f"{installer.PYTHON_ROOT}/{source_path}"
        install_rows.append(
            {
                "path": install_path,
                "size": int(size),
                "sha256": digest,
                "uid": 0,
                "gid": 0,
                "mode": stat.S_IFREG | (0o555 if int(mode) & 0o111 else 0o444),
            }
        )
        source_map.append({"source_path": source_path, "install_path": install_path})
    install_rows.sort(key=lambda row: str(row["path"]))
    source_map.sort(key=lambda row: row["source_path"])
    if len(install_rows) != len(seen):
        raise MaterializerError("CPython install projection denominator drifted")
    return install_rows, source_map


def _record_digest(payload: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
    return "sha256=" + encoded.decode("ascii")


def _zip_member_mode(info: zipfile.ZipInfo) -> int:
    mode = (info.external_attr >> 16) & 0xFFFF
    if mode == 0:
        return stat.S_IFREG | 0o644
    return mode


def inspect_wheel(
    path: Path,
    *,
    distribution: str,
    enforce_pin: bool = True,
) -> dict[str, object]:
    """Validate one exact wheel and return its immutable install projection."""

    spec = _WHEEL_SPECS.get(distribution)
    if spec is None:
        raise MaterializerError("wheel distribution is not in the exact-three roster")
    path = Path(path)
    raw = _read_regular(
        path,
        label=f"wheel {distribution}",
        required_mode=0o444 if enforce_pin else None,
    )
    if enforce_pin and (
        path.name != spec["filename"] or len(raw) != spec["size"] or _sha256(raw) != spec["sha256"]
    ):
        raise MaterializerError("wheel preimage drifted from the exact release pin")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError) as error:
        raise MaterializerError("wheel is not a readable ZIP") from error
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > _ZIP_MAX_MEMBERS:
            raise MaterializerError("wheel member denominator invalid")
        path_tree: list[tuple[str, bool]] = []
        for info in infos:
            if info.orig_filename != info.filename or "\x00" in info.orig_filename:
                raise MaterializerError("wheel raw member name is noncanonical")
            if info.flag_bits & 0x1:
                raise MaterializerError("wheel member encryption or size invalid")
            member_path = _safe_relative_path(info.filename.rstrip("/"), label="wheel member")
            path_tree.append((member_path, info.is_dir()))
        _validate_path_tree(path_tree, label="wheel member")
        members: dict[str, tuple[zipfile.ZipInfo, bytes]] = {}
        collision_keys: set[str] = set()
        total = 0
        for info in infos:
            member_path = _safe_relative_path(info.filename.rstrip("/"), label="wheel member")
            collision_key = unicodedata.normalize("NFC", member_path).casefold()
            if collision_key in collision_keys:
                raise MaterializerError("wheel member duplicate or filesystem collision")
            collision_keys.add(collision_key)
            mode = _zip_member_mode(info)
            if info.is_dir():
                if not stat.S_ISDIR(mode):
                    raise MaterializerError("wheel directory metadata invalid")
                continue
            if not stat.S_ISREG(mode):
                raise MaterializerError("wheel member is symlink or non-regular")
            if info.file_size > _ZIP_MAX_MEMBER_BYTES:
                raise MaterializerError("wheel member encryption or size invalid")
            if is_forbidden_cpython_path(member_path):
                raise MaterializerError("wheel contains a forbidden Python startup path")
            try:
                payload = archive.read(info)
            except (RuntimeError, OSError, zipfile.BadZipFile) as error:
                raise MaterializerError("wheel member read failed") from error
            if len(payload) != info.file_size:
                raise MaterializerError("wheel member size drifted")
            total += len(payload)
            if total > _ZIP_MAX_TOTAL_BYTES:
                raise MaterializerError("wheel expanded closure is too large")
            members[member_path] = (info, payload)

    record_path = f"{spec['dist_info']}/RECORD"
    record = members.get(record_path)
    if record is None:
        raise MaterializerError("wheel RECORD is missing")
    try:
        record_rows = list(csv.reader(io.StringIO(record[1].decode("utf-8"), newline="")))
    except (UnicodeDecodeError, csv.Error) as error:
        raise MaterializerError("wheel RECORD is malformed") from error
    record_by_path: dict[str, tuple[str, str]] = {}
    for row in record_rows:
        if len(row) != 3:
            raise MaterializerError("wheel RECORD row invalid")
        member_path = _safe_relative_path(row[0], label="wheel RECORD")
        if member_path in record_by_path:
            raise MaterializerError("wheel RECORD path duplicated")
        record_by_path[member_path] = (row[1], row[2])
    if set(record_by_path) != set(members):
        raise MaterializerError("wheel RECORD is incomplete or contains extras")
    for member_path, (_info, payload) in members.items():
        digest, size = record_by_path[member_path]
        if member_path == record_path:
            if digest or size:
                raise MaterializerError("wheel RECORD self-row must be unhashed")
        elif digest != _record_digest(payload) or size != str(len(payload)):
            raise MaterializerError("wheel RECORD measurement mismatch")

    rows: list[dict[str, object]] = []
    install_map: list[dict[str, str]] = []
    payloads: dict[str, bytes] = {}
    for member_path in sorted(members, key=str.encode):
        info, payload = members[member_path]
        install_path = f"{installer.PYTHON_SITE_PACKAGES}/{member_path}"
        mode = _zip_member_mode(info)
        rows.append(
            {
                "path": install_path,
                "size": len(payload),
                "sha256": _sha256(payload),
                "uid": 0,
                "gid": 0,
                "mode": stat.S_IFREG | (0o555 if mode & 0o111 else 0o444),
            }
        )
        install_map.append(
            {
                "distribution": distribution,
                "member_path": member_path,
                "install_path": install_path,
            }
        )
        payloads[member_path] = payload
    return {
        "distribution": distribution,
        "wheel_size": len(raw),
        "wheel_sha256": _sha256(raw),
        "entries": rows,
        "install_map": install_map,
        "payloads": payloads,
    }


def _read_canonical_json(path: Path, *, label: str) -> dict[str, Any]:
    raw = _read_regular(path, label=label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MaterializerError(f"{label} is malformed") from error
    if not isinstance(value, dict):
        raise MaterializerError(f"{label} is not an object")
    return value


def census_node_capsule(
    metis_root: Path = DEFAULT_METIS_ROOT,
    *,
    evidence_path: Path = DEFAULT_CAPSULE_EVIDENCE,
    enforce_pin: bool = True,
) -> tuple[dict[str, object], dict[str, bytes]]:
    """Reconstruct the exact 32+1790+5 capsule without executing it.

    The existing native-evidence generator owns the audited Git-object,
    node_modules and five-control reconstruction logic.  This wrapper invokes
    only those metadata/read functions, then independently cross-binds every
    byte to the frozen evidence roster used by the installer.
    """

    from runtime import w3_native_evidence as native_evidence

    evidence = _read_canonical_json(Path(evidence_path), label="capsule evidence")
    if evidence.get("metis") != {
        "revision": native_evidence.METIS_REVISION,
        "tree": native_evidence.METIS_TREE,
    }:
        raise MaterializerError("capsule evidence Git identity drifted")
    try:
        source_rows, source_payloads = native_evidence._ast_census(Path(metis_root))
        package_rows, package_payloads, _identities = native_evidence._package_closure(
            Path(metis_root)
        )
        controls = native_evidence._control_bytes(
            Path(metis_root),
            native_evidence.oracles.CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"],
        )
    except native_evidence.EvidenceError as error:
        raise MaterializerError("capsule source reconstruction failed") from error

    roles = {
        **{str(row["path"]): "git-archive" for row in source_rows},
        **{str(row["path"]): "tooling" for row in package_rows},
        ".metis-oracle-identity.json": "tooling",
        ".metis-oracle/native_ts_loader.mjs": "loader",
        ".metis-oracle/runner.ts": "runner",
        "tooling/package-lock.json": "tooling",
        "tooling/package.json": "tooling",
    }
    payloads = {**source_payloads, **package_payloads, **controls}
    rows = [
        {
            "mode": 0o444,
            "path": path,
            "role": roles[path],
            "sha256": _sha256(raw),
            "size": len(raw),
        }
        for path, raw in sorted(payloads.items(), key=lambda item: item[0].encode("utf-8"))
    ]
    roster = {
        "files": len(rows),
        "bytes": sum(int(row["size"]) for row in rows),
        "sha256": installer._roster_hash(rows),
        "entries": rows,
    }
    frozen = evidence.get("capsule_closure")
    if not isinstance(frozen, Mapping) or frozen.get("rows") != rows:
        raise MaterializerError("capsule bytes do not match the frozen evidence roster")
    if enforce_pin and (
        roster["files"] != installer.NODE_CAPSULE_FILES
        or roster["bytes"] != installer.NODE_CAPSULE_BYTES
        or roster["sha256"] != installer.NODE_CAPSULE_ROSTER_SHA256
    ):
        raise MaterializerError("capsule closure drifted from the release pin")
    return roster, payloads


def capture_cpython(
    root: Path = DEFAULT_CPYTHON_ROOT,
) -> tuple[dict[str, object], dict[str, bytes]]:
    """Return the pinned CPython census plus independently remeasured bytes."""

    census = census_cpython(root)
    payloads: dict[str, bytes] = {}
    for row in census["entries"]:
        relative = str(row["path"])
        raw = _read_regular(Path(root) / relative, label=f"CPython source {relative}")
        if len(raw) != row["size"] or _sha256(raw) != row["sha256"]:
            raise MaterializerError("CPython source changed between census and capture")
        payloads[relative] = raw
    return census, payloads


def inspect_exact_wheels(
    wheel_root: Path = DEFAULT_WHEEL_ROOT,
) -> dict[str, dict[str, object]]:
    """Close and cross-check all three wheel install partitions."""

    wheel_root = Path(wheel_root)
    try:
        _validate_absolute_ancestry(wheel_root, expect_directory=True)
        observed = list(os.scandir(wheel_root))
    except OSError as error:
        raise MaterializerError("exact-three wheel root unavailable") from error
    except MaterializerError as error:
        raise MaterializerError("exact-three wheel root ancestry invalid") from error
    names = sorted(entry.name for entry in observed)
    expected = sorted(str(spec["filename"]) for spec in _WHEEL_SPECS.values())
    if names != expected:
        raise MaterializerError("exact-three wheel root has missing or extra leaves")
    for entry in observed:
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError as error:
            raise MaterializerError("exact-three wheel leaf unavailable") from error
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise MaterializerError("exact-three wheel leaf is non-regular")
    result = {
        name: inspect_wheel(
            wheel_root / str(spec["filename"]),
            distribution=name,
        )
        for name, spec in _WHEEL_SPECS.items()
    }
    all_entries = [row for wheel in result.values() for row in wheel["entries"]]
    validate_global_install_paths(all_entries)
    paths = [str(row["path"]) for row in all_entries]
    if len(paths) != len(set(paths)):
        raise MaterializerError("cross-wheel install collision")
    return result


def project_capsule_install(
    census: Mapping[str, object],
) -> list[dict[str, object]]:
    """Project the exact capsule census into the immutable release slot."""

    entries = census.get("entries") if isinstance(census, Mapping) else None
    if not isinstance(entries, list):
        raise MaterializerError("capsule census invalid")
    rows = [
        {
            "path": f"{installer.RELEASE_ROOT}/capsule/{row['path']}",
            "size": int(row["size"]),
            "sha256": str(row["sha256"]),
            "uid": 0,
            "gid": 0,
            "mode": stat.S_IFREG | int(row["mode"]),
        }
        for row in entries
    ]
    rows.sort(key=lambda row: str(row["path"]))
    validate_global_install_paths(rows)
    return rows


def project_project_modules() -> tuple[list[dict[str, object]], dict[str, bytes]]:
    """Capture the exact twelve installed Python project modules."""

    if set(_PROJECT_SOURCE_PATHS) != set(installer.REQUIRED_PROJECT_PACKAGE_PATHS):
        raise MaterializerError("project module roster drifted from installer contract")
    rows: list[dict[str, object]] = []
    payloads: dict[str, bytes] = {}
    for install_path, source_path in sorted(_PROJECT_SOURCE_PATHS.items()):
        raw = _read_regular(source_path, label=f"project module {source_path.name}")
        payloads[install_path] = raw
        rows.append(
            {
                "path": install_path,
                "size": len(raw),
                "sha256": _sha256(raw),
                "uid": 0,
                "gid": 0,
                "mode": stat.S_IFREG | 0o444,
            }
        )
    return rows, payloads


def build_fixture_registry(
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    semantic_registry_path: Path = DEFAULT_SEMANTIC_REGISTRY_PATH,
) -> bytes:
    """Build the exact five-role public-synthetic selector registry."""

    from runtime import w3_installed_worker as installed_worker

    document = _read_canonical_json(Path(candidates_path), label="public candidates")
    semantic_document = _read_canonical_json(
        Path(semantic_registry_path), label="public semantic registry"
    )

    def manifest_hash(value: Mapping[str, object]) -> str:
        body = {key: item for key, item in value.items() if key != "manifest_sha256"}
        payload = json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return _sha256(payload)

    if (
        document.get("manifest_sha256") != _CANDIDATE_MANIFEST_SHA256
        or manifest_hash(document) != _CANDIDATE_MANIFEST_SHA256
        or semantic_document.get("manifest_sha256") != _SEMANTIC_REGISTRY_SHA256
        or manifest_hash(semantic_document) != _SEMANTIC_REGISTRY_SHA256
    ):
        raise MaterializerError("public fixture manifests drifted from their exact pins")
    candidates = document.get("candidates")
    specs = semantic_document.get("specs")
    if not isinstance(candidates, list) or len(candidates) != 3 or not isinstance(specs, list):
        raise MaterializerError("public candidates roster invalid")
    if len(specs) != 3 or any(not isinstance(item, Mapping) for item in [*candidates, *specs]):
        raise MaterializerError("public candidate and semantic denominators invalid")
    by_family: dict[str, Mapping[str, object]] = {}
    by_id: dict[str, Mapping[str, object]] = {}
    for candidate in candidates:
        family = candidate.get("family")
        candidate_id = candidate.get("candidate_id")
        if (
            family not in {"F-1", "F-2", "F-3"}
            or not isinstance(candidate_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", candidate_id) is None
            or family in by_family
            or candidate_id in by_id
        ):
            raise MaterializerError("public candidate family or id roster invalid")
        by_family[str(family)] = candidate
        by_id[candidate_id] = candidate
    specs_by_id = {str(spec.get("candidate_id")): spec for spec in specs}
    if (
        set(by_family) != {"F-1", "F-2", "F-3"}
        or set(specs_by_id) != set(by_id)
        or len(specs_by_id) != 3
    ):
        raise MaterializerError("public candidates family roster invalid")
    for candidate_id, candidate in by_id.items():
        spec = specs_by_id[candidate_id]
        semantic = spec.get("semantic_spec")
        semantic_payload = json.dumps(
            semantic,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        spec_body = {key: value for key, value in spec.items() if key != "spec_sha256"}
        spec_payload = json.dumps(
            spec_body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if (
            candidate.get("semantic_spec") != semantic
            or candidate.get("family") != spec.get("family")
            or spec.get("semantic_spec_sha256") != _sha256(semantic_payload)
            or spec.get("spec_sha256") != _sha256(spec_payload)
            or candidate.get("root_evidence", {}).get("semantic_spec_sha256")
            != spec.get("semantic_spec_sha256")
        ):
            raise MaterializerError("public candidate semantic cross-binding invalid")
    runtime = dict(_RUNTIME_EXPECTATIONS)
    if set(runtime) != installed_worker.RUNNER_RUNTIME_FIELDS:
        raise MaterializerError("runtime expectation field roster drifted")
    entries: list[dict[str, object]] = []
    for family, role, source_field in _FIXTURE_ROLE_FIELDS:
        candidate = by_family[family]
        semantic = candidate.get("semantic_spec")
        source = candidate.get(source_field)
        if not isinstance(semantic, Mapping) or not isinstance(source, str) or not source:
            raise MaterializerError("public candidate semantic input invalid")
        workspace = semantic.get("workspace_sources")
        if not isinstance(workspace, dict):
            raise MaterializerError("public candidate workspace invalid")
        filename = semantic.get("filename")
        execution_mode = semantic.get("execution_mode")
        endpoint = semantic.get("endpoint")
        if (
            not isinstance(filename, str)
            or _safe_relative_path(filename, label="fixture filename") != filename
            or not filename.endswith(".metis")
            or execution_mode != "endpoint"
            or not isinstance(endpoint, str)
            or not endpoint
            or any(
                not isinstance(name, str)
                or _safe_relative_path(name, label="workspace source") != name
                or not name.endswith(".metis")
                or name == filename
                or not isinstance(value, str)
                or not value
                for name, value in workspace.items()
            )
        ):
            raise MaterializerError("public candidate request identity invalid")
        request = {
            "schema_version": 1,
            "source": source,
            "filename": filename,
            "execution_mode": execution_mode,
            "endpoint": endpoint,
            "metis_root": f"snapshot://{_METIS_REVISION}/{_METIS_TREE}",
            "metis_revision": _METIS_REVISION,
            "metis_tree": _METIS_TREE,
            "workspace_sources": [
                {"filename": name, "source": value} for name, value in sorted(workspace.items())
            ],
        }
        inputs = {"source": _sha256(source.encode("utf-8"))}
        inputs.update(
            {
                f"workspace:{name}": _sha256(value.encode("utf-8"))
                for name, value in sorted(workspace.items())
            }
        )
        entries.append(
            {
                "task": f"{candidate['candidate_id']}-{role}",
                "inputs": dict(sorted(inputs.items())),
                "oracle_request": request,
                "runtime_expectations": runtime,
            }
        )
    tasks = [str(row["task"]) for row in entries]
    if len(entries) != 5 or len(tasks) != len(set(tasks)):
        raise MaterializerError("public fixture five-role denominator drifted")
    registry = {
        "schema_version": installed_worker.FIXTURE_REGISTRY_VERSION,
        "kind": installed_worker.FIXTURE_REGISTRY_KIND,
        "entries": entries,
    }
    installed_worker.validate_fixture_registry(registry)
    return json.dumps(
        registry,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def build_broker_config(install_entries: Sequence[Mapping[str, object]]) -> bytes:
    """Render and validate the fixed installed broker configuration."""

    from runtime import w3_broker_executor as executor
    from runtime import w3_broker_protocol as protocol

    config = {
        "schema_version": executor.CONFIG_VERSION,
        "kind": executor.CONFIG_KIND,
        "mode": protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
        "authority_path": installer.AUTHORITY_REGISTRY_PATH,
        "public_key_registry_path": installer.PUBLIC_KEY_REGISTRY_PATH,
        "fixture_registry_path": installer.PUBLIC_FIXTURE_REGISTRY_PATH,
        "private_key_path": installer.SIGNING_KEY_PATH,
        "ledger_path": installer.BROKER_LEDGER_PATH,
        "public_receipt_journal_path": installer.PUBLIC_RECEIPT_JOURNAL_PATH,
        "publication_root": installer.PUBLICATION_ACTIVE,
        "installed_roster_path_map": installer.authority_roster_path_map(install_entries),
        "max_inflight": 1,
    }
    executor._validate_config(config)
    return protocol.canonical_bytes(config)


def build_launchd_plists() -> dict[str, bytes]:
    """Capture and semantically reparse the exact tracked launchd plists."""

    by_role = {
        "broker-plist": (
            installer.BROKER_PLIST_LABEL,
            PROJECT_ROOT / "packaging/launchd/com.metis.model1.w3-broker.plist.in",
        ),
        "launcher-plist": (
            installer.LAUNCHER_PLIST_LABEL,
            PROJECT_ROOT / "packaging/launchd/com.metis.model1.w3-launcher.plist.in",
        ),
        "anchor-plist": (
            installer.ANCHOR_PLIST_LABEL,
            PROJECT_ROOT / "packaging/launchd/com.metis.model1.w3-anchor.plist.in",
        ),
    }
    result: dict[str, bytes] = {}
    for role, (label, path) in by_role.items():
        payload = _read_regular(path, label=f"tracked {role}")
        installer.validate_launchd_plist_bytes(payload, label=label)
        result[role] = payload
    return result


def _run_build(argv: Sequence[str]) -> None:
    try:
        completed = subprocess.run(
            list(argv),
            cwd="/",
            env=dict(installer.BOOTSTRAP_BUILD_ENVIRONMENT),
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise MaterializerError("native build could not start deterministically") from error
    if completed.returncode != 0 or completed.stdout or completed.stderr:
        raise MaterializerError("native build failed or emitted undeclared output")


def _native_build_argv(
    source: Path,
    output: Path,
    *,
    definitions: Sequence[str],
) -> list[str]:
    return [
        installer.BOOTSTRAP_COMPILER_PATH,
        "-std=c17",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-Werror",
        "-arch",
        installer.BOOTSTRAP_ARCHITECTURE,
        f"-mmacosx-version-min={installer.BOOTSTRAP_DEPLOYMENT_TARGET}",
        "-isysroot",
        installer.BOOTSTRAP_SDK_PATH,
        "-Wl,-no_uuid",
        *definitions,
        str(source),
        "-o",
        str(output),
    ]


def _inspect_macho(payload_path: Path, payload: bytes) -> None:
    commands = (
        ["/usr/bin/file", str(payload_path)],
        ["/usr/bin/otool", "-l", str(payload_path)],
        ["/usr/bin/otool", "-L", str(payload_path)],
    )
    outputs: list[bytes] = []
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                cwd="/",
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise MaterializerError("Mach-O inspection unavailable") from error
        if completed.returncode != 0 or completed.stderr:
            raise MaterializerError("Mach-O inspection failed")
        outputs.append(completed.stdout)
    linked = [
        line.strip().split(b" ", 1)[0] for line in outputs[2].splitlines()[1:] if line.strip()
    ]
    if (
        b"Mach-O 64-bit executable arm64" not in outputs[0]
        or b"LC_UUID" in outputs[1]
        or linked != [b"/usr/lib/libSystem.B.dylib"]
        or b"/Users/" in payload
    ):
        raise MaterializerError("native binary architecture or UUID drifted")


def _verify_native_toolchain() -> None:
    linker = _read_regular(Path(installer.BOOTSTRAP_LINKER_PATH), label="pinned linker")
    if (
        len(linker) != installer.BOOTSTRAP_LINKER_SIZE
        or _sha256(linker) != installer.BOOTSTRAP_LINKER_SHA256
    ):
        raise MaterializerError("pinned linker preimage drifted")
    sdk_link = Path(installer.BOOTSTRAP_SDK_PATH)
    try:
        sdk_info = os.stat(sdk_link, follow_symlinks=False)
        sdk_text = os.readlink(sdk_link)
    except OSError as error:
        raise MaterializerError("pinned SDK link unavailable") from error
    if not stat.S_ISLNK(sdk_info.st_mode) or sdk_text != "MacOSX.sdk":
        raise MaterializerError("pinned SDK link drifted")
    sdk = sdk_link.parent / sdk_text
    _validate_absolute_ancestry(sdk, expect_directory=True)
    settings = _read_regular(sdk / "SDKSettings.json", label="SDK settings")
    if (
        len(settings) != installer.BOOTSTRAP_SDK_SETTINGS_SIZE
        or _sha256(settings) != installer.BOOTSTRAP_SDK_SETTINGS_SHA256
    ):
        raise MaterializerError("SDK settings preimage drifted")
    libsystem_link = sdk / "usr/lib/libSystem.tbd"
    try:
        libsystem_info = os.stat(libsystem_link, follow_symlinks=False)
        libsystem_text = os.readlink(libsystem_link)
    except OSError as error:
        raise MaterializerError("SDK libSystem link unavailable") from error
    if (
        not stat.S_ISLNK(libsystem_info.st_mode)
        or libsystem_text != "libSystem.B.tbd"
        or libsystem_info.st_uid != 0
        or libsystem_info.st_gid != 0
        or stat.S_IMODE(libsystem_info.st_mode) != 0o755
        or libsystem_info.st_nlink != 1
    ):
        raise MaterializerError("SDK libSystem link drifted")
    libsystem = _read_regular(sdk / "usr/lib/libSystem.B.tbd", label="SDK libSystem")
    commondigest = _read_regular(
        sdk / "usr/include/CommonCrypto/CommonDigest.h",
        label="SDK CommonDigest",
    )
    if (
        len(libsystem) != installer.BOOTSTRAP_LIBSYSTEM_SIZE
        or _sha256(libsystem) != installer.BOOTSTRAP_LIBSYSTEM_SHA256
        or len(commondigest) != installer.BOOTSTRAP_COMMONDIGEST_SIZE
        or _sha256(commondigest) != installer.BOOTSTRAP_COMMONDIGEST_SHA256
    ):
        raise MaterializerError("SDK native link inputs drifted")


def build_native_binaries() -> dict[str, bytes]:
    """Build launcher and two distinct shims twice without executing them."""

    compiler = _read_regular(
        Path(installer.BOOTSTRAP_COMPILER_PATH),
        label="pinned compiler",
    )
    if (
        len(compiler) != installer.BOOTSTRAP_COMPILER_SIZE
        or _sha256(compiler) != installer.BOOTSTRAP_COMPILER_SHA256
    ):
        raise MaterializerError("pinned compiler preimage drifted")
    _verify_native_toolchain()
    launcher_source = PROJECT_ROOT / "runtime" / "w3_privileged_launcher.c"
    shim_source = PROJECT_ROOT / "runtime" / "w3_socket_activation_shim.c"
    launcher_raw = _read_regular(launcher_source, label="launcher source")
    shim_raw = _read_regular(shim_source, label="shim source")
    if (
        len(launcher_raw) != 69_509
        or _sha256(launcher_raw)
        != "sha256:a992adb3dfaff865dd741e69a85835a6f25dc12da7bf320821cd24ccd8197cf7"
        or len(shim_raw) != 5_363
        or _sha256(shim_raw)
        != "sha256:be43112ea26b46499a69051664fc23bba98801b576b6266ae0728876e7487c5c"
    ):
        raise MaterializerError("native source release pin drifted")
    definitions = {
        "launcher": (
            "-DW3_PRIVILEGED_LAUNCHER_PHASE_B=1",
            f"-DW3_BROKER_UID={installer.BROKER_UID}",
            f"-DW3_BROKER_GID={installer.BROKER_GID}",
            f"-DW3_RUNNER_UID={installer.RUNNER_UID}",
            f"-DW3_RUNNER_GID={installer.RUNNER_GID}",
        ),
        "broker-socket-shim": (
            '-DW3_SHIM_LISTENER_NAME="BrokerListener"',
            '-DW3_SHIM_MODULE_NAME="runtime.w3_broker_service"',
        ),
        "anchor-socket-shim": (
            '-DW3_SHIM_LISTENER_NAME="AnchorListener"',
            '-DW3_SHIM_MODULE_NAME="runtime.w3_anchor_service"',
        ),
    }
    build_root = Path(tempfile.mkdtemp(prefix="w3-phase-b-native-", dir="/private/var/tmp"))
    try:
        launcher_snapshot = build_root / "sources/w3_privileged_launcher.c"
        shim_snapshot = build_root / "sources/w3_socket_activation_shim.c"
        _write_exclusive(launcher_snapshot, launcher_raw, 0o444)
        _write_exclusive(shim_snapshot, shim_raw, 0o444)
        sources = {
            "launcher": launcher_snapshot,
            "broker-socket-shim": shim_snapshot,
            "anchor-socket-shim": shim_snapshot,
        }
        result: dict[str, bytes] = {}
        for role in ("launcher", "broker-socket-shim", "anchor-socket-shim"):
            builds: list[bytes] = []
            for index in ("a", "b"):
                build_directory = build_root / index
                build_directory.mkdir(mode=0o700, exist_ok=True)
                output = build_directory / role
                _run_build(
                    _native_build_argv(
                        sources[role],
                        output,
                        definitions=definitions[role],
                    )
                )
                raw = _read_regular(output, label=f"native {role} build {index}")
                _inspect_macho(output, raw)
                builds.append(raw)
            if builds[0] != builds[1]:
                raise MaterializerError(f"native {role} builds are not reproducible")
            expected_size, expected_digest = installer.NATIVE_ARTIFACT_PINS[role]
            if len(builds[0]) != expected_size or _sha256(builds[0]) != expected_digest:
                raise MaterializerError(f"native {role} release output pin drifted")
            result[role] = builds[0]
        if result["broker-socket-shim"] == result["anchor-socket-shim"]:
            raise MaterializerError("native socket shims are not distinct")
        return result
    finally:
        shutil.rmtree(build_root)


def verify_stage0_builds(
    build_a: Path = DEFAULT_STAGE0_BUILD_A,
    build_b: Path = DEFAULT_STAGE0_BUILD_B,
) -> bytes:
    """Remeasure the two frozen, never-executed Stage-0 build outputs."""

    first = _read_regular(Path(build_a), label="Stage0 build A")
    second = _read_regular(Path(build_b), label="Stage0 build B")
    if (
        first != second
        or len(first) != installer.BOOTSTRAP_BINARY_SIZE
        or _sha256(first) != installer.BOOTSTRAP_BINARY_SHA256
    ):
        raise MaterializerError("Stage0 reproducible binary pin drifted")
    return first


def _roster(entries: Sequence[Mapping[str, object]]) -> dict[str, object]:
    rows = sorted((dict(row) for row in entries), key=lambda row: str(row["path"]))
    paths = [str(row["path"]) for row in rows]
    if not rows or len(paths) != len(set(paths)):
        raise MaterializerError("roster paths are empty or duplicated")
    return {
        "files": len(rows),
        "bytes": sum(int(row["size"]) for row in rows),
        "sha256": installer._roster_hash(rows),
        "entries": rows,
    }


def _bootstrap_build_provenance() -> dict[str, object]:
    sdk = installer.BOOTSTRAP_SDK_PATH
    digest = installer.BOOTSTRAP_BINARY_SHA256
    return {
        "compiler_path": installer.BOOTSTRAP_COMPILER_PATH,
        "compiler_size": installer.BOOTSTRAP_COMPILER_SIZE,
        "compiler_sha256": installer.BOOTSTRAP_COMPILER_SHA256,
        "compiler_version": installer.BOOTSTRAP_COMPILER_VERSION,
        "linker_path": installer.BOOTSTRAP_LINKER_PATH,
        "linker_size": installer.BOOTSTRAP_LINKER_SIZE,
        "linker_sha256": installer.BOOTSTRAP_LINKER_SHA256,
        "linker_version": installer.BOOTSTRAP_LINKER_VERSION,
        "sdk_path": sdk,
        "sdk_version": installer.BOOTSTRAP_SDK_VERSION,
        "sdk_settings_path": f"{sdk}/SDKSettings.json",
        "sdk_settings_size": installer.BOOTSTRAP_SDK_SETTINGS_SIZE,
        "sdk_settings_sha256": installer.BOOTSTRAP_SDK_SETTINGS_SHA256,
        "libsystem_link_path": f"{sdk}/usr/lib/libSystem.tbd",
        "libsystem_link_text": "libSystem.B.tbd",
        "libsystem_link_uid": 0,
        "libsystem_link_gid": 0,
        "libsystem_link_mode": 0o755,
        "libsystem_link_nlink": 1,
        "libsystem_resolved_path": f"{sdk}/usr/lib/libSystem.B.tbd",
        "libsystem_size": installer.BOOTSTRAP_LIBSYSTEM_SIZE,
        "libsystem_sha256": installer.BOOTSTRAP_LIBSYSTEM_SHA256,
        "commondigest_path": f"{sdk}/usr/include/CommonCrypto/CommonDigest.h",
        "commondigest_size": installer.BOOTSTRAP_COMMONDIGEST_SIZE,
        "commondigest_sha256": installer.BOOTSTRAP_COMMONDIGEST_SHA256,
        "architecture": installer.BOOTSTRAP_ARCHITECTURE,
        "deployment_target": installer.BOOTSTRAP_DEPLOYMENT_TARGET,
        "argv": list(installer.BOOTSTRAP_BUILD_ARGV),
        "environment": dict(installer.BOOTSTRAP_BUILD_ENVIRONMENT),
        "cwd": "/",
        "repeat_builds": 2,
        "build_hashes": [digest, digest],
        "build_status": "reproducible-two-builds",
        "reproducible_binary_sha256": digest,
        "mach_o_architectures": [installer.BOOTSTRAP_ARCHITECTURE],
        "linked_dylibs": ["/usr/lib/libSystem.B.dylib"],
        "lc_uuid_present": False,
        "forbidden_path_strings_present": False,
    }


def _bootstrap_block() -> dict[str, object]:
    return {
        "version": 1,
        "source_root": installer.BOOTSTRAP_SOURCE_ROOT,
        "target_root": installer.STAGED_BUNDLE_ROOT,
        "descriptor_path": installer.BOOTSTRAP_DESCRIPTOR_PATH,
        "descriptor_magic": installer.BOOTSTRAP_DESCRIPTOR_MAGIC,
        "descriptor_max_bytes": installer.BOOTSTRAP_DESCRIPTOR_MAX_BYTES,
        "file_count_max": installer.BOOTSTRAP_FILE_COUNT_MAX,
        "total_bytes_max": installer.BOOTSTRAP_TOTAL_BYTES_MAX,
        "bootstrap_install_path": installer.BOOTSTRAP_BINARY_PATH,
        "bootstrap_source_path": "runtime/w3_installer_bootstrap.c",
        "bootstrap_source_size": installer.BOOTSTRAP_SOURCE_SIZE,
        "bootstrap_source_sha256": installer.BOOTSTRAP_SOURCE_SHA256,
        "bootstrap_binary_size": installer.BOOTSTRAP_BINARY_SIZE,
        "bootstrap_binary_sha256": installer.BOOTSTRAP_BINARY_SHA256,
        "build_provenance": _bootstrap_build_provenance(),
        "manifest_relative_path": installer.BOOTSTRAP_MANIFEST_RELATIVE_PATH,
        "plan_relative_path": installer.BOOTSTRAP_PLAN_RELATIVE_PATH,
        "python_path": installer.STAGED_INSTALL_TREE + installer.EXPECTED_ARTIFACT_PATHS["python"],
        "executor_module": installer.BOOTSTRAP_EXECUTOR_MODULE,
        "python_argv": ["-I", "-B", "-m", installer.BOOTSTRAP_EXECUTOR_MODULE],
        "cwd": "/",
        "sterile_environment": {"PATH": installer.BOOTSTRAP_STERILE_PATH},
        "admin_precondition": [
            "trusted-/usr/bin/install-copy-bootstrap-and-descriptor",
            "external-/usr/bin/shasum-remeasure-before-exec",
            "trusted-/usr/bin/env--ignore-environment-before-stage-0-exec",
            "no-repository-python-before-stage-0",
        ],
        "admin_invocation_template": installer.admin_invocation_template(),
    }


def _installed_row(
    path: str,
    payload: bytes,
    metadata: tuple[int, int, int],
) -> dict[str, object]:
    uid, gid, mode = metadata
    return {
        "path": path,
        "size": len(payload),
        "sha256": _sha256(payload),
        "uid": uid,
        "gid": gid,
        "mode": mode,
    }


def _source_row(path: str, payload: bytes) -> dict[str, object]:
    return {"path": path, "size": len(payload), "sha256": _sha256(payload)}


def _write_exclusive(path: Path, payload: bytes, mode: int) -> None:
    if not path.is_absolute() or len(path.parts) < 2:
        raise MaterializerError("materialized output path invalid")
    components = path.parts[1:]
    if any(part in {"", ".", ".."} for part in components):
        raise MaterializerError("materialized output path invalid")
    parent_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = -1
    created = False
    initial: os.stat_result | None = None
    try:
        for component in components[:-1]:
            try:
                child_fd = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError:
                os.mkdir(component, 0o700, dir_fd=parent_fd)
                os.fsync(parent_fd)
                child_fd = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            info = os.fstat(child_fd)
            if not stat.S_ISDIR(info.st_mode):
                os.close(child_fd)
                raise MaterializerError("materialized output ancestry is not a directory")
            os.close(parent_fd)
            parent_fd = child_fd
        descriptor = os.open(
            components[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode,
            dir_fd=parent_fd,
        )
        created = True
        initial = os.fstat(descriptor)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise MaterializerError("materialized file write stalled")
            offset += written
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        os.fsync(parent_fd)
        info = os.fstat(descriptor)
        named = os.stat(components[-1], dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_size != len(payload)
            or stat.S_IMODE(info.st_mode) != mode
            or _identity(named) != _identity(info)
            or initial is None
            or (initial.st_dev, initial.st_ino) != (info.st_dev, info.st_ino)
        ):
            raise MaterializerError("materialized file metadata invalid")
        read_fd = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            measured_parts: list[bytes] = []
            while True:
                chunk = os.read(read_fd, _READ_CHUNK)
                if not chunk:
                    break
                measured_parts.append(chunk)
            measured_info = os.fstat(read_fd)
        finally:
            os.close(read_fd)
        if _identity(measured_info) != _identity(info) or b"".join(measured_parts) != payload:
            raise MaterializerError("materialized file bytes changed")
    except BaseException as error:
        if created and initial is not None:
            try:
                named = os.stat(components[-1], dir_fd=parent_fd, follow_symlinks=False)
                if (named.st_dev, named.st_ino) == (initial.st_dev, initial.st_ino):
                    os.unlink(components[-1], dir_fd=parent_fd)
                    os.fsync(parent_fd)
            except OSError:
                pass
        if isinstance(error, FileExistsError):
            raise MaterializerError("materialized output would clobber an existing leaf") from error
        if isinstance(error, OSError):
            raise MaterializerError("materialized file publication failed") from error
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)


def _mkdir_exclusive_open(
    path: Path,
    mode: int = 0o700,
) -> tuple[int, int, str, os.stat_result]:
    if not path.is_absolute() or len(path.parts) < 2:
        raise MaterializerError("materialization root path invalid")
    components = path.parts[1:]
    if any(part in {"", ".", ".."} for part in components):
        raise MaterializerError("materialization root path invalid")
    parent_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = -1
    created = False
    try:
        for component in components[:-1]:
            child_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            os.close(parent_fd)
            parent_fd = child_fd
        os.mkdir(components[-1], mode, dir_fd=parent_fd)
        created = True
        os.fsync(parent_fd)
        root_fd = os.open(
            components[-1],
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        info = os.fstat(root_fd)
        named = os.stat(components[-1], dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) != mode
            or _identity(info) != _identity(named)
        ):
            raise MaterializerError("materialization root metadata invalid")
        return parent_fd, root_fd, components[-1], info
    except BaseException as error:
        if root_fd >= 0:
            os.close(root_fd)
        if created:
            try:
                os.rmdir(components[-1], dir_fd=parent_fd)
                os.fsync(parent_fd)
            except OSError:
                pass
        os.close(parent_fd)
        if isinstance(error, FileExistsError):
            raise MaterializerError("materialization root already exists") from error
        if isinstance(error, OSError):
            raise MaterializerError("materialization root ancestry invalid") from error
        raise


def _mkdir_exclusive(path: Path, mode: int = 0o700) -> os.stat_result:
    parent_fd, root_fd, _name, info = _mkdir_exclusive_open(path, mode)
    os.close(root_fd)
    os.close(parent_fd)
    return info


def _mkdir_exclusive_at(
    parent_fd: int,
    name: str,
    mode: int = 0o700,
) -> tuple[int, os.stat_result]:
    if _safe_relative_path(name, label="materialization root") != name:
        raise MaterializerError("materialization root name invalid")
    created: os.stat_result | None = None
    root_fd = -1
    try:
        os.mkdir(name, mode, dir_fd=parent_fd)
        created = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(created.st_mode) or stat.S_IMODE(created.st_mode) != mode:
            raise MaterializerError("materialization root metadata invalid")
        root_fd = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        bound = os.fstat(root_fd)
        if _identity(bound) != _identity(created):
            raise MaterializerError("materialization root identity changed")
        os.fsync(parent_fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if _identity(named) != _identity(bound):
            raise MaterializerError("materialization root identity changed")
        return root_fd, bound
    except BaseException as error:
        if root_fd >= 0:
            os.close(root_fd)
        if created is not None:
            try:
                named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if (named.st_dev, named.st_ino) == (created.st_dev, created.st_ino):
                    os.rmdir(name, dir_fd=parent_fd)
                    os.fsync(parent_fd)
            except OSError:
                pass
        if isinstance(error, FileExistsError):
            raise MaterializerError("materialization root already exists") from error
        if isinstance(error, OSError):
            raise MaterializerError("materialization root creation failed") from error
        raise


def _open_directory_no_follow(path: Path) -> int:
    """Open an absolute directory through held, no-follow descriptors."""

    path = Path(path)
    if (
        not path.is_absolute()
        or len(path.parts) < 2
        or any(part in {"", ".", ".."} for part in path.parts[1:])
    ):
        raise MaterializerError("publication directory path invalid")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise MaterializerError("publication path is not a directory")
        return descriptor
    except BaseException as error:
        os.close(descriptor)
        if isinstance(error, MaterializerError):
            raise
        raise MaterializerError("publication directory ancestry invalid") from error


def _open_parent_no_follow(path: Path) -> tuple[int, str]:
    path = Path(path)
    if (
        not path.is_absolute()
        or len(path.parts) < 2
        or any(part in {"", ".", ".."} for part in path.parts[1:])
    ):
        raise MaterializerError("publication leaf path invalid")
    return _open_directory_no_follow(path.parent), path.name


def _rename_exclusive(
    source_parent_fd: int,
    source_name: str,
    target_parent_fd: int,
    target_name: str,
) -> None:
    """Atomically move one entry without replacing a target on Darwin/Linux."""

    library = ctypes.CDLL(None, use_errno=True)
    source_raw = os.fsencode(source_name)
    target_raw = os.fsencode(target_name)
    if sys.platform == "darwin":
        operation = getattr(library, "renameatx_np", None)
        flag = 0x00000004  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        operation = getattr(library, "renameat2", None)
        flag = 0x00000001  # RENAME_NOREPLACE
    else:
        operation = None
        flag = 0
    if operation is None:
        raise MaterializerError("exclusive rename primitive unavailable")
    operation.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    operation.restype = ctypes.c_int
    if operation(source_parent_fd, source_raw, target_parent_fd, target_raw, flag) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), target_name)


def _bind_renamed_entry(
    target_parent_fd: int,
    target_name: str,
    expected: os.stat_result,
    *,
    kind: str,
) -> os.stat_result:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if kind == "directory":
        flags |= os.O_DIRECTORY
    descriptor = os.open(target_name, flags, dir_fd=target_parent_fd)
    try:
        bound = os.fstat(descriptor)
        named = os.stat(target_name, dir_fd=target_parent_fd, follow_symlinks=False)
        expected_type = (
            stat.S_ISDIR(bound.st_mode) if kind == "directory" else stat.S_ISREG(bound.st_mode)
        )
        if (
            not expected_type
            or (bound.st_dev, bound.st_ino) != (expected.st_dev, expected.st_ino)
            or _identity(named) != _identity(bound)
        ):
            raise MaterializerError("exclusive rename target identity changed")
        return bound
    finally:
        os.close(descriptor)


def _rename_exclusive_recorded(
    source_parent_fd: int,
    source_name: str,
    target_parent_fd: int,
    target_name: str,
    expected: os.stat_result,
    *,
    kind: str,
    record_effect: Any,
) -> os.stat_result:
    """Record a completed rename even if an injected wrapper raises afterward."""

    try:
        _rename_exclusive(
            source_parent_fd,
            source_name,
            target_parent_fd,
            target_name,
        )
    except BaseException:
        try:
            bound = _bind_renamed_entry(
                target_parent_fd,
                target_name,
                expected,
                kind=kind,
            )
        except (OSError, MaterializerError):
            pass
        else:
            record_effect(bound)
        raise
    bound = _bind_renamed_entry(
        target_parent_fd,
        target_name,
        expected,
        kind=kind,
    )
    record_effect(bound)
    return bound


def _read_regular_at(
    parent_fd: int,
    name: str,
    *,
    label: str,
    required_mode: int | None = None,
) -> tuple[bytes, os.stat_result]:
    """Remeasure a named no-follow leaf while its parent remains held."""

    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=parent_fd,
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise MaterializerError(f"{label} is not a single-link regular file")
        if required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode:
            raise MaterializerError(f"{label} mode invalid")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, _READ_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(before) != _identity(named):
            raise MaterializerError(f"{label} identity changed")
        payload = b"".join(chunks)
        if len(payload) != before.st_size:
            raise MaterializerError(f"{label} size changed")
        return payload, before
    except OSError as error:
        raise MaterializerError(f"{label} unavailable") from error
    finally:
        os.close(descriptor)


def _scan_tree_at(
    root_fd: int,
    *,
    label: str,
) -> tuple[list[dict[str, object]], set[str]]:
    """Return an exact regular-file and directory census through held dirfds."""

    rows: list[dict[str, object]] = []
    directories: set[str] = set()

    def visit(directory_fd: int, prefix: str) -> None:
        try:
            names = sorted(os.listdir(directory_fd), key=lambda value: value.encode("utf-8"))
        except (OSError, UnicodeEncodeError) as error:
            raise MaterializerError(f"{label} directory census failed") from error
        for name in names:
            relative = f"{prefix}/{name}" if prefix else name
            try:
                canonical = _safe_relative_path(relative, label=label)
                observed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except (OSError, UnicodeError) as error:
                raise MaterializerError(f"{label} entry unavailable") from error
            if stat.S_ISDIR(observed.st_mode):
                child_fd = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                try:
                    if _identity(os.fstat(child_fd)) != _identity(observed):
                        raise MaterializerError(f"{label} directory identity changed")
                    directories.add(canonical)
                    visit(child_fd, canonical)
                    named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if _identity(named) != _identity(observed):
                        raise MaterializerError(f"{label} directory identity changed")
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(observed.st_mode):
                raise MaterializerError(f"{label} contains a symlink or special entry")
            mode = stat.S_IMODE(observed.st_mode)
            if mode not in {0o444, 0o555}:
                raise MaterializerError(f"{label} file mode invalid")
            payload, measured = _read_regular_at(
                directory_fd,
                name,
                label=f"{label} {canonical}",
                required_mode=mode,
            )
            if _identity(measured) != _identity(observed):
                raise MaterializerError(f"{label} file identity changed")
            rows.append(
                {
                    "path": canonical,
                    "size": len(payload),
                    "sha256": _sha256(payload),
                    "mode": f"{mode:04o}",
                }
            )

    visit(root_fd, "")
    rows.sort(key=lambda row: str(row["path"]).encode("utf-8"))
    return rows, directories


def _expected_directories(rows: Sequence[Mapping[str, object]]) -> set[str]:
    output: set[str] = set()
    for row in rows:
        parts = str(row["path"]).split("/")
        output.update("/".join(parts[:index]) for index in range(1, len(parts)))
    return output


def _verify_tree_at(
    root_fd: int,
    expected_rows: Sequence[Mapping[str, object]],
    *,
    label: str,
) -> list[dict[str, object]]:
    observed, directories = _scan_tree_at(root_fd, label=label)
    expected = sorted(
        (dict(row) for row in expected_rows),
        key=lambda row: str(row["path"]).encode("utf-8"),
    )
    if observed != expected or directories != _expected_directories(expected):
        raise MaterializerError(f"{label} exact tree differs from descriptor")
    return observed


def _unlink_same_identity(path: Path, expected: os.stat_result) -> bool:
    """Unlink only the still-named inode created by the current transaction."""

    parent_fd, name = _open_parent_no_follow(path)
    try:
        try:
            named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if (named.st_dev, named.st_ino) != (expected.st_dev, expected.st_ino):
            return False
        os.unlink(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        return True
    finally:
        os.close(parent_fd)


def _write_relative_exclusive(
    root_fd: int,
    relative: str,
    payload: bytes,
    mode: int,
    *,
    owned_entries: dict[str, tuple[int, int, str]] | None = None,
    after_component_create: Any | None = None,
) -> os.stat_result:
    """Create one file below a held root without resolving the root again."""

    canonical = _safe_relative_path(relative, label="materialized output")
    parts = canonical.split("/")
    parent_fd = os.dup(root_fd)
    descriptor = -1
    initial: os.stat_result | None = None
    try:
        for index, component in enumerate(parts[:-1], start=1):
            prefix = "/".join(parts[:index])
            child_fd = -1
            try:
                try:
                    observed = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
                    child_fd = os.open(
                        component,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=parent_fd,
                    )
                except FileNotFoundError:
                    os.mkdir(component, 0o700, dir_fd=parent_fd)
                    observed = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
                    if not stat.S_ISDIR(observed.st_mode):
                        raise MaterializerError(
                            "created output component is not a directory"
                        ) from None
                    if owned_entries is not None:
                        owned_entries[prefix] = (
                            observed.st_dev,
                            observed.st_ino,
                            "directory",
                        )
                    if after_component_create is not None:
                        after_component_create(prefix, observed)
                    child_fd = os.open(
                        component,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=parent_fd,
                    )
                    bound = os.fstat(child_fd)
                    if (bound.st_dev, bound.st_ino) != (
                        observed.st_dev,
                        observed.st_ino,
                    ):
                        raise MaterializerError(
                            "created output component identity changed"
                        ) from None
                    os.fsync(parent_fd)
                    named = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
                    if (named.st_dev, named.st_ino) != (bound.st_dev, bound.st_ino):
                        raise MaterializerError(
                            "created output component identity changed"
                        ) from None
                else:
                    bound = os.fstat(child_fd)
                    expected_owned = (
                        owned_entries.get(prefix) if owned_entries is not None else None
                    )
                    if (
                        not stat.S_ISDIR(observed.st_mode)
                        or (bound.st_dev, bound.st_ino) != (observed.st_dev, observed.st_ino)
                        or expected_owned is None
                        or expected_owned != (bound.st_dev, bound.st_ino, "directory")
                    ):
                        raise MaterializerError("output component is foreign or changed")
            except BaseException:
                if child_fd >= 0:
                    os.close(child_fd)
                raise
            os.close(parent_fd)
            parent_fd = child_fd
        descriptor = os.open(
            parts[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode,
            dir_fd=parent_fd,
        )
        initial = os.fstat(descriptor)
        if owned_entries is not None:
            owned_entries[canonical] = (initial.st_dev, initial.st_ino, "file")
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise MaterializerError("materialized file write stalled")
            offset += written
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        os.fsync(parent_fd)
        final = os.fstat(descriptor)
        if (
            initial is None
            or (initial.st_dev, initial.st_ino) != (final.st_dev, final.st_ino)
            or not stat.S_ISREG(final.st_mode)
            or final.st_nlink != 1
            or final.st_size != len(payload)
            or stat.S_IMODE(final.st_mode) != mode
        ):
            raise MaterializerError("materialized file metadata invalid")
        measured, named = _read_regular_at(
            parent_fd,
            parts[-1],
            label=f"materialized output {canonical}",
            required_mode=mode,
        )
        if measured != payload or _identity(named) != _identity(final):
            raise MaterializerError("materialized file bytes changed")
        return final
    except BaseException as error:
        if initial is not None:
            try:
                named = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
                if (named.st_dev, named.st_ino) == (initial.st_dev, initial.st_ino):
                    os.unlink(parts[-1], dir_fd=parent_fd)
                    os.fsync(parent_fd)
                    if owned_entries is not None:
                        owned_entries.pop(canonical, None)
            except OSError:
                pass
        if isinstance(error, FileExistsError):
            raise MaterializerError("materialized output would clobber an existing leaf") from error
        if isinstance(error, OSError):
            raise MaterializerError("materialized file publication failed") from error
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)


def _open_relative_parent(root_fd: int, relative: str) -> tuple[int, str]:
    canonical = _safe_relative_path(relative, label="owned output")
    parts = canonical.split("/")
    parent_fd = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            child_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            os.close(parent_fd)
            parent_fd = child_fd
        return parent_fd, parts[-1]
    except BaseException:
        os.close(parent_fd)
        raise


def _verify_owned_entries(
    root_fd: int,
    owned_entries: Mapping[str, tuple[int, int, str]],
) -> None:
    for relative, (device, inode, kind) in owned_entries.items():
        parent_fd, name = _open_relative_parent(root_fd, relative)
        try:
            observed = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        finally:
            os.close(parent_fd)
        if (
            (observed.st_dev, observed.st_ino) != (device, inode)
            or (kind == "directory" and not stat.S_ISDIR(observed.st_mode))
            or (kind == "file" and not stat.S_ISREG(observed.st_mode))
        ):
            raise MaterializerError("owned output identity changed")


def _cleanup_owned_entries(
    root_fd: int,
    owned_entries: Mapping[str, tuple[int, int, str]],
) -> None:
    ordered = sorted(
        owned_entries.items(),
        key=lambda item: (item[0].count("/"), item[1][2] == "directory"),
        reverse=True,
    )
    failures: list[str] = []
    for relative, (device, inode, kind) in ordered:
        try:
            parent_fd, name = _open_relative_parent(root_fd, relative)
        except (OSError, MaterializerError):
            failures.append(relative)
            continue
        try:
            try:
                observed = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if (observed.st_dev, observed.st_ino) != (device, inode):
                failures.append(relative)
                continue
            if kind == "file" and stat.S_ISREG(observed.st_mode):
                os.unlink(name, dir_fd=parent_fd)
            elif kind == "directory" and stat.S_ISDIR(observed.st_mode):
                os.rmdir(name, dir_fd=parent_fd)
            else:
                failures.append(relative)
                continue
            os.fsync(parent_fd)
            try:
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                failures.append(relative)
        except OSError:
            failures.append(relative)
        finally:
            os.close(parent_fd)
    if failures:
        raise MaterializerError(
            "owned output cleanup incomplete: " + ", ".join(sorted(set(failures)))
        )


def _clear_owned_tree(root_fd: int) -> None:
    """Remove a tree through its held root descriptor without following links."""

    for name in os.listdir(root_fd):
        observed = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if stat.S_ISDIR(observed.st_mode):
            child_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=root_fd,
            )
            try:
                if _identity(os.fstat(child_fd)) != _identity(observed):
                    raise MaterializerError("owned tree directory identity changed")
                _clear_owned_tree(child_fd)
            finally:
                os.close(child_fd)
            named = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            if not stat.S_ISDIR(named.st_mode) or (named.st_dev, named.st_ino) != (
                observed.st_dev,
                observed.st_ino,
            ):
                raise MaterializerError("owned tree directory identity changed")
            os.rmdir(name, dir_fd=root_fd)
            continue
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            raise MaterializerError("owned tree contains an unremovable foreign entry")
        named = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if _identity(named) != _identity(observed):
            raise MaterializerError("owned tree file identity changed")
        os.unlink(name, dir_fd=root_fd)
    os.fsync(root_fd)


def _write_tree_exclusive(
    root: Path,
    files: Mapping[str, tuple[bytes, int]],
    *,
    after_root_open: Any | None = None,
    after_component_create: Any | None = None,
) -> os.stat_result:
    """Publish a complete private tree under one held root descriptor."""

    parent_fd, root_fd, root_name, root_info = _mkdir_exclusive_open(Path(root))
    owned_entries: dict[str, tuple[int, int, str]] = {}
    try:
        if after_root_open is not None:
            after_root_open()
        expected_rows: list[dict[str, object]] = []
        for relative, (payload, mode) in sorted(files.items()):
            _write_relative_exclusive(
                root_fd,
                relative,
                payload,
                mode,
                owned_entries=owned_entries,
                after_component_create=after_component_create,
            )
            expected_rows.append(
                {
                    "path": relative,
                    "size": len(payload),
                    "sha256": _sha256(payload),
                    "mode": f"{mode:04o}",
                }
            )
        _verify_tree_at(root_fd, expected_rows, label="materialized staging tree")
        _verify_owned_entries(root_fd, owned_entries)
        current = os.fstat(root_fd)
        named = os.stat(root_name, dir_fd=parent_fd, follow_symlinks=False)
        absolute = _validate_absolute_ancestry(Path(root), expect_directory=True)
        if (
            (current.st_dev, current.st_ino) != (root_info.st_dev, root_info.st_ino)
            or _identity(named) != _identity(current)
            or _identity(absolute) != _identity(current)
        ):
            raise MaterializerError("staging root identity changed")
        return root_info
    except BaseException as error:
        try:
            _cleanup_owned_entries(root_fd, owned_entries)
            named = os.stat(root_name, dir_fd=parent_fd, follow_symlinks=False)
            if (named.st_dev, named.st_ino) == (root_info.st_dev, root_info.st_ino):
                os.rmdir(root_name, dir_fd=parent_fd)
                os.fsync(parent_fd)
            else:
                raise MaterializerError("staging root identity changed")
        except (OSError, MaterializerError) as cleanup_error:
            raise MaterializerError(
                f"staging tree rollback incomplete after {error}"
            ) from cleanup_error
        raise
    finally:
        os.close(root_fd)
        os.close(parent_fd)


def _write_tree_exclusive_at(
    parent_fd: int,
    root_name: str,
    files: Mapping[str, tuple[bytes, int]],
) -> os.stat_result:
    """Held-parent variant used by the production transaction workspace."""

    root_fd, root_info = _mkdir_exclusive_at(parent_fd, root_name)
    owned_entries: dict[str, tuple[int, int, str]] = {}
    try:
        expected_rows: list[dict[str, object]] = []
        for relative, (payload, mode) in sorted(files.items()):
            _write_relative_exclusive(
                root_fd,
                relative,
                payload,
                mode,
                owned_entries=owned_entries,
            )
            expected_rows.append(
                {
                    "path": relative,
                    "size": len(payload),
                    "sha256": _sha256(payload),
                    "mode": f"{mode:04o}",
                }
            )
        _verify_tree_at(root_fd, expected_rows, label="materialized staging tree")
        _verify_owned_entries(root_fd, owned_entries)
        current = os.fstat(root_fd)
        named = os.stat(root_name, dir_fd=parent_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (root_info.st_dev, root_info.st_ino) or _identity(
            named
        ) != _identity(current):
            raise MaterializerError("staging root identity changed")
        return root_info
    except BaseException as error:
        try:
            _cleanup_owned_entries(root_fd, owned_entries)
            named = os.stat(root_name, dir_fd=parent_fd, follow_symlinks=False)
            if (named.st_dev, named.st_ino) == (root_info.st_dev, root_info.st_ino):
                os.rmdir(root_name, dir_fd=parent_fd)
                os.fsync(parent_fd)
            else:
                raise MaterializerError("staging root identity changed")
        except (OSError, MaterializerError) as cleanup_error:
            raise MaterializerError(
                f"staging tree rollback incomplete after {error}"
            ) from cleanup_error
        raise
    finally:
        os.close(root_fd)


def build_materialization(
    staging_root: Path,
    *,
    publish: bool = False,
    cpython_root: Path = DEFAULT_CPYTHON_ROOT,
    metis_root: Path = DEFAULT_METIS_ROOT,
    node_path: Path = DEFAULT_NODE_PATH,
    wheel_root: Path = DEFAULT_WHEEL_ROOT,
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    semantic_registry_path: Path = DEFAULT_SEMANTIC_REGISTRY_PATH,
    _staging_parent_fd: int | None = None,
) -> dict[str, object]:
    """Build and validate one complete no-clobber Phase-B source tree.

    ``staging_root`` is caller-selected so two independent temporary builds can
    be compared before production publication.  This function never publishes
    into the fixed source root; use :func:`materialize_transaction` for that.
    """

    if publish:
        raise MaterializerError("build_materialization cannot publish; use transaction API")
    staging_root = Path(staging_root)
    if not staging_root.is_absolute():
        raise MaterializerError("staging root must be absolute")

    cpython_census, cpython_payloads = capture_cpython(Path(cpython_root))
    cpython_rows, source_install_map = project_cpython_install(cpython_census["entries"])
    wheel_material = inspect_exact_wheels(Path(wheel_root))
    capsule_census, capsule_payloads = census_node_capsule(Path(metis_root))
    capsule_rows = project_capsule_install(capsule_census)
    project_rows, project_payloads = project_project_modules()
    native_payloads = build_native_binaries()
    node_payload = _read_regular(Path(node_path), label="pinned Node binary")
    if len(node_payload) != installer.NODE_SIZE or _sha256(node_payload) != installer.NODE_SHA256:
        raise MaterializerError("pinned Node binary drifted")
    policy_payload = _read_regular(
        PROJECT_ROOT / "packaging/seatbelt/w3-runner.sb",
        label="concrete Seatbelt policy",
    )
    installer.validate_concrete_policy_bytes(policy_payload)
    fixture_payload = build_fixture_registry(
        Path(candidates_path),
        Path(semantic_registry_path),
    )
    plist_payloads = build_launchd_plists()

    install_rows: list[dict[str, object]] = []
    install_payloads: dict[str, bytes] = {}

    def add_install(row: Mapping[str, object], payload: bytes) -> None:
        path = str(row["path"])
        if (
            path in install_payloads
            or len(payload) != row["size"]
            or _sha256(payload) != row["sha256"]
        ):
            raise MaterializerError("install partition collision or measurement drift")
        install_rows.append(dict(row))
        install_payloads[path] = payload

    cpython_by_source = {
        str(row["source_path"]): str(row["install_path"]) for row in source_install_map
    }
    cpython_by_install = {str(row["path"]): row for row in cpython_rows}
    for source_path, install_path in sorted(cpython_by_source.items()):
        add_install(cpython_by_install[install_path], cpython_payloads[source_path])

    wheel_install_map: list[dict[str, str]] = []
    for _distribution, wheel in wheel_material.items():
        rows_by_path = {str(row["path"]): row for row in wheel["entries"]}
        for mapping in wheel["install_map"]:
            install_path = str(mapping["install_path"])
            member_path = str(mapping["member_path"])
            add_install(rows_by_path[install_path], wheel["payloads"][member_path])
            wheel_install_map.append(dict(mapping))
    wheel_install_map.sort(
        key=lambda row: (row["distribution"], row["member_path"], row["install_path"])
    )

    for row in project_rows:
        add_install(row, project_payloads[str(row["path"])])
    for row in capsule_rows:
        relative = str(row["path"])[len(f"{installer.RELEASE_ROOT}/capsule/") :]
        add_install(row, capsule_payloads[relative])

    fixed_payloads: dict[str, bytes] = {
        "launcher": native_payloads["launcher"],
        "broker-socket-shim": native_payloads["broker-socket-shim"],
        "anchor-socket-shim": native_payloads["anchor-socket-shim"],
        "node": node_payload,
        "policy": policy_payload,
        "fixture-registry": fixture_payload,
        **plist_payloads,
    }
    for role, payload in fixed_payloads.items():
        add_install(
            _installed_row(
                installer.EXPECTED_ARTIFACT_PATHS[role],
                payload,
                installer.EXPECTED_ARTIFACT_METADATA[role],
            ),
            payload,
        )

    provisional = sorted(install_rows, key=lambda row: str(row["path"]))
    broker_config = build_broker_config(provisional)
    add_install(
        _installed_row(
            installer.BROKER_CONFIG_PATH,
            broker_config,
            installer.EXPECTED_ARTIFACT_METADATA["broker-config"],
        ),
        broker_config,
    )
    install_rows.sort(key=lambda row: str(row["path"]))
    validate_global_install_paths(install_rows)

    artifact_payloads: dict[str, bytes] = {}
    artifacts: list[dict[str, object]] = []
    install_by_path = {str(row["path"]): row for row in install_rows}
    for role in sorted(installer.EXPECTED_ARTIFACT_PATHS):
        install_path = installer.EXPECTED_ARTIFACT_PATHS[role]
        row = install_by_path.get(install_path)
        payload = install_payloads.get(install_path)
        if row is None or payload is None:
            raise MaterializerError(f"required artifact role missing: {role}")
        source_path = f"{installer.STAGED_BUNDLE_ROOT}/artifacts/{role}"
        artifacts.append(
            {
                "role": role,
                "source_path": source_path,
                "source_size": row["size"],
                "source_sha256": row["sha256"],
                "install_path": install_path,
                "size": row["size"],
                "sha256": row["sha256"],
            }
        )
        artifact_payloads[role] = payload

    physical: dict[str, tuple[bytes, int]] = {}

    def add_physical(relative: str, payload: bytes, mode: int) -> None:
        relative = _safe_relative_path(relative, label="materialized source")
        if relative in physical:
            raise MaterializerError("materialized source path collision")
        physical[relative] = (payload, mode)

    source_rows: list[dict[str, object]] = []
    for role, payload in artifact_payloads.items():
        install_row = install_by_path[installer.EXPECTED_ARTIFACT_PATHS[role]]
        mode = 0o555 if int(install_row["mode"]) & 0o111 else 0o444
        relative = f"artifacts/{role}"
        add_physical(relative, payload, mode)
        source_rows.append(_source_row(f"{installer.STAGED_BUNDLE_ROOT}/{relative}", payload))
    for row in install_rows:
        install_path = str(row["path"])
        relative = "install-root" + install_path
        payload = install_payloads[install_path]
        mode = 0o555 if int(row["mode"]) & 0o111 else 0o444
        add_physical(relative, payload, mode)
        source_rows.append(_source_row(installer.STAGED_INSTALL_TREE + install_path, payload))
    for relative, payload in cpython_payloads.items():
        physical_path = f"source-census/cpython-3.13.3/{relative}"
        add_physical(physical_path, payload, 0o444)
        source_rows.append(
            _source_row(f"{installer.PYTHON_SOURCE_CENSUS_ROOT}/{relative}", payload)
        )
    for relative, payload in capsule_payloads.items():
        physical_path = f"source-census/node-capsule/{relative}"
        add_physical(physical_path, payload, 0o444)
        source_rows.append(_source_row(f"{installer.NODE_SOURCE_CENSUS_ROOT}/{relative}", payload))

    dependencies: list[dict[str, object]] = []
    for pinned in installer.PYTHON_DEPENDENCIES:
        name = str(pinned["name"])
        spec = _WHEEL_SPECS[name]
        wheel_path = Path(wheel_root) / str(spec["filename"])
        payload = _read_regular(wheel_path, label=f"wheel {name}", required_mode=0o444)
        relative = f"wheels/{spec['filename']}"
        add_physical(relative, payload, 0o444)
        source_rows.append(_source_row(installer.WHEEL_SOURCE_PATHS[name], payload))
        dependencies.append(
            {
                "name": name,
                "version": pinned["version"],
                "wheel_path": installer.WHEEL_SOURCE_PATHS[name],
                "wheel_size": len(payload),
                "wheel_sha256": _sha256(payload),
            }
        )

    _validate_path_tree([(path, False) for path in physical], label="materialized source")
    source_roster = _roster(source_rows)
    install_roster = _roster(install_rows)
    python_rows = [
        row for row in install_rows if str(row["path"]).startswith(installer.PYTHON_ROOT + "/")
    ]
    executable_paths = sorted(str(row["path"]) for row in python_rows if int(row["mode"]) & 0o111)
    artifact_hash = _sha256(
        json.dumps(
            artifacts,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    )
    manifest: dict[str, object] = {
        "schema_version": 1,
        "kind": "w3-phase-b-install-bundle",
        "status": "frozen",
        "outcome": "PHASE_B_INSTALLABLE_UNEXECUTED",
        "nonclaims": list(installer.NONCLAIMS),
        "release_content_roster_sha256": installer.release_content_roster_digest(install_rows),
        "principals": {role: dict(value) for role, value in installer.FIXED_PRINCIPALS.items()},
        "services": [
            installer.LAUNCHER_PLIST_LABEL,
            installer.ANCHOR_PLIST_LABEL,
            installer.BROKER_PLIST_LABEL,
        ],
        "installer_bootstrap": _bootstrap_block(),
        "artifacts": artifacts,
        "artifact_roster_sha256": artifact_hash,
        "python_runtime": {
            "implementation": "CPython",
            "version": installer.PYTHON_VERSION,
            "source_census": cpython_census,
            "source_install_map": source_install_map,
            "wheel_install_map": wheel_install_map,
            "project_install_paths": sorted(_PROJECT_SOURCE_PATHS),
            "executable_paths": executable_paths,
            "staged_roster": _roster(python_rows),
            "symlink_policy": "no-symlinks-normalize-aliases-before-freeze",
            "editable_paths_allowed": False,
        },
        "python_dependencies": dependencies,
        "node_capsule": {
            "node_version": installer.NODE_VERSION,
            "node_sha256": installer.NODE_SHA256,
            "source_census": capsule_census,
            "evidence_status": "blocked-static-capsule-only",
            "host_credit": False,
        },
        "source_roster": source_roster,
        "install_roster": install_roster,
        "authority_roster_paths": sorted(
            installer.authority_roster_path_map(install_rows).values()
        ),
        "directories": installer.expected_directory_roster(install_rows),
        "backend_roster_sha256": installer.backend_roster_digest(),
        "bundle_sha256": None,
    }
    manifest["bundle_sha256"] = _sha256(
        installer.canonical_bundle_bytes(manifest, omit_digest=True)
    )
    frozen = installer.validate_bundle_manifest(manifest, require_frozen=True)
    manifest_payload = installer.canonical_bundle_bytes(frozen)
    plan = installer.plan_install(
        {
            "authority_id": installer.AUTHORITY_ID,
            "bundle_sha256": manifest["bundle_sha256"],
            "release_content_roster_sha256": str(
                manifest["release_content_roster_sha256"]
            ).removeprefix("sha256:"),
        }
    )
    installer.validate_install_plan(plan, bundle_manifest=frozen)
    plan_payload = installer.canonical_plan_bytes(plan)
    descriptor_files = installer.expected_bootstrap_descriptor_files(
        frozen,
        manifest_payload=manifest_payload,
        plan_payload=plan_payload,
    )
    descriptor_payload = installer.bootstrap_descriptor_bytes(
        bootstrap_sha256=installer.BOOTSTRAP_BINARY_SHA256,
        manifest_sha256=_sha256(manifest_payload),
        plan_sha256=_sha256(plan_payload),
        files=descriptor_files,
    )
    admin = installer.admin_invocation_document(
        descriptor_payload=descriptor_payload,
        plan_payload=plan_payload,
        manifest_payload=manifest_payload,
    )
    installer.validate_admin_invocation_document(
        admin,
        descriptor_payload=descriptor_payload,
        plan_payload=plan_payload,
        manifest_payload=manifest_payload,
    )
    admin_payload = json.dumps(
        admin,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    physical[installer.BOOTSTRAP_MANIFEST_RELATIVE_PATH] = (manifest_payload, 0o444)
    physical[installer.BOOTSTRAP_PLAN_RELATIVE_PATH] = (plan_payload, 0o444)
    descriptor_by_path = {str(row["path"]): row for row in descriptor_files}
    if set(descriptor_by_path) != set(physical):
        raise MaterializerError("descriptor and physical source trees differ")
    for relative, (payload, mode) in physical.items():
        expected = descriptor_by_path[relative]
        if (
            expected["size"] != len(payload)
            or expected["sha256"] != _sha256(payload)
            or expected["mode"] != f"{mode:04o}"
        ):
            raise MaterializerError("descriptor physical source binding drifted")

    stage0_payload = verify_stage0_builds()
    if _staging_parent_fd is None:
        _write_tree_exclusive(staging_root, physical)
    else:
        _write_tree_exclusive_at(_staging_parent_fd, staging_root.name, physical)
    return {
        "source_root": str(staging_root),
        "manifest": frozen,
        "manifest_payload": manifest_payload,
        "plan": plan,
        "plan_payload": plan_payload,
        "descriptor_payload": descriptor_payload,
        "admin_invocation": admin,
        "admin_invocation_payload": admin_payload,
        "descriptor_files": descriptor_files,
        "stage0_payload": stage0_payload,
    }


def _measure_wheels_at(root_fd: int) -> dict[str, tuple[int, int, int, str, int]]:
    try:
        observed = os.stat("wheels", dir_fd=root_fd, follow_symlinks=False)
        wheel_fd = os.open(
            "wheels",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
    except OSError as error:
        raise MaterializerError("fixed wheel directory unavailable") from error
    try:
        if _identity(os.fstat(wheel_fd)) != _identity(observed):
            raise MaterializerError("fixed wheel directory identity changed")
        names = sorted(os.listdir(wheel_fd))
        expected_names = sorted(str(spec["filename"]) for spec in _WHEEL_SPECS.values())
        if names != expected_names:
            raise MaterializerError("fixed source root wheel set drifted")
        result: dict[str, tuple[int, int, int, str, int]] = {}
        specs_by_filename = {str(spec["filename"]): spec for spec in _WHEEL_SPECS.values()}
        for name in names:
            payload, info = _read_regular_at(
                wheel_fd,
                name,
                label=f"fixed wheel {name}",
                required_mode=0o444,
            )
            spec = specs_by_filename[name]
            digest = _sha256(payload)
            if len(payload) != spec["size"] or digest != spec["sha256"]:
                raise MaterializerError("fixed wheel pin drifted")
            result[name] = (info.st_dev, info.st_ino, len(payload), digest, 0o444)
        return result
    finally:
        os.close(wheel_fd)


def _source_root_preflight(root_fd: int) -> dict[str, tuple[int, int, int, str, int]]:
    try:
        names = set(os.listdir(root_fd))
    except OSError as error:
        raise MaterializerError("fixed source root census failed") from error
    allowed = {"wheels", *_SOURCE_PUBLICATION_CHILDREN}
    if "wheels" not in names or not names.issubset(allowed):
        raise MaterializerError("fixed source root contains an unknown child")
    return _measure_wheels_at(root_fd)


def _child_expected_rows(
    descriptor_files: Sequence[Mapping[str, object]],
    child: str,
) -> list[dict[str, object]]:
    prefix = child + "/"
    rows = [
        {
            **dict(row),
            "path": str(row["path"])[len(prefix) :],
        }
        for row in descriptor_files
        if str(row["path"]).startswith(prefix)
    ]
    if not rows:
        raise MaterializerError(f"descriptor lacks source child {child}")
    return rows


def _verify_child_at(
    root_fd: int,
    child: str,
    expected_rows: Sequence[Mapping[str, object]],
    *,
    label: str,
) -> os.stat_result:
    try:
        before = os.stat(child, dir_fd=root_fd, follow_symlinks=False)
        child_fd = os.open(
            child,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
    except OSError as error:
        raise MaterializerError(f"{label} unavailable") from error
    try:
        bound = os.fstat(child_fd)
        if not stat.S_ISDIR(before.st_mode) or (bound.st_dev, bound.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise MaterializerError(f"{label} identity changed")
        _verify_tree_at(child_fd, expected_rows, label=label)
        after = os.stat(child, dir_fd=root_fd, follow_symlinks=False)
        current = os.fstat(child_fd)
        if _identity(after) != _identity(current):
            raise MaterializerError(f"{label} identity changed")
        return current
    finally:
        os.close(child_fd)


def _adopt_or_publish_file_at(
    parent_fd: int,
    name: str,
    payload: bytes,
    mode: int,
    *,
    label: str,
    owned_entries: dict[str, tuple[int, int, str]],
    staging_fd: int,
    staging_name: str,
) -> tuple[str, os.stat_result]:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        staged_payload, staged_info = _read_regular_at(
            staging_fd,
            staging_name,
            label=f"staged {label}",
            required_mode=mode,
        )
        if staged_payload != payload:
            raise MaterializerError(f"staged {label} bytes differ") from None

        def record_effect(bound: os.stat_result) -> None:
            owned_entries[name] = (bound.st_dev, bound.st_ino, "file")

        try:
            _rename_exclusive_recorded(
                staging_fd,
                staging_name,
                parent_fd,
                name,
                staged_info,
                kind="file",
                record_effect=record_effect,
            )
        except OSError as error:
            raise MaterializerError(f"atomic {label} publication failed") from error
        os.fsync(staging_fd)
        os.fsync(parent_fd)
        measured, info = _read_regular_at(
            parent_fd,
            name,
            label=label,
            required_mode=mode,
        )
        if measured != payload or (info.st_dev, info.st_ino) != (
            staged_info.st_dev,
            staged_info.st_ino,
        ):
            raise MaterializerError(f"published {label} identity changed") from None
        return "created", info
    measured, info = _read_regular_at(
        parent_fd,
        name,
        label=label,
        required_mode=mode,
    )
    if measured != payload:
        raise MaterializerError(f"{label} canonical bytes differ")
    return "adopted", info


def _rows_digest(rows: Sequence[Mapping[str, object]]) -> str:
    payload = json.dumps(
        sorted((dict(row) for row in rows), key=lambda row: str(row["path"])),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return _sha256(payload)


def _prepare_transaction_context(
    source_root: Path,
    manifest_root: Path,
    staging_parent: Path,
) -> tuple[
    int,
    int,
    int,
    os.stat_result,
    os.stat_result,
    dict[str, tuple[int, int, int, str, int]],
    int,
    os.stat_result,
    str,
]:
    source_fd = -1
    manifest_fd = -1
    staging_parent_fd = -1
    workspace_fd = -1
    workspace_info: os.stat_result | None = None
    workspace_name = ""
    try:
        source_fd = _open_directory_no_follow(source_root)
        manifest_fd = _open_directory_no_follow(manifest_root)
        staging_parent_fd = _open_directory_no_follow(staging_parent)
        source_initial = os.fstat(source_fd)
        manifest_initial = os.fstat(manifest_fd)
        wheels_before = _source_root_preflight(source_fd)
        inspect_exact_wheels(source_root / "wheels")
        for _attempt in range(128):
            candidate = ".w3-phase-b-materialize." + secrets.token_hex(12)
            try:
                workspace_fd, workspace_info = _mkdir_exclusive_at(
                    staging_parent_fd,
                    candidate,
                )
            except MaterializerError as error:
                if str(error) == "materialization root already exists":
                    continue
                raise
            workspace_name = candidate
            break
        if workspace_fd < 0 or workspace_info is None:
            raise MaterializerError("unable to allocate an exclusive transaction workspace")
        return (
            source_fd,
            manifest_fd,
            staging_parent_fd,
            source_initial,
            manifest_initial,
            wheels_before,
            workspace_fd,
            workspace_info,
            workspace_name,
        )
    except BaseException:
        if workspace_fd >= 0:
            try:
                _clear_owned_tree(workspace_fd)
                named = os.stat(
                    workspace_name,
                    dir_fd=staging_parent_fd,
                    follow_symlinks=False,
                )
                if workspace_info is not None and (
                    named.st_dev,
                    named.st_ino,
                ) == (workspace_info.st_dev, workspace_info.st_ino):
                    os.rmdir(workspace_name, dir_fd=staging_parent_fd)
            except (OSError, MaterializerError):
                pass
            os.close(workspace_fd)
        if staging_parent_fd >= 0:
            os.close(staging_parent_fd)
        if manifest_fd >= 0:
            os.close(manifest_fd)
        if source_fd >= 0:
            os.close(source_fd)
        raise


def _verify_workspace_children(
    workspace_fd: int,
    children: Mapping[str, os.stat_result],
) -> None:
    names = set(os.listdir(workspace_fd))
    if names != set(children):
        raise MaterializerError("transaction workspace contains a foreign entry")
    for name, expected in children.items():
        observed = os.stat(name, dir_fd=workspace_fd, follow_symlinks=False)
        if not stat.S_ISDIR(observed.st_mode) or (observed.st_dev, observed.st_ino) != (
            expected.st_dev,
            expected.st_ino,
        ):
            raise MaterializerError("transaction workspace child identity changed")


def _cleanup_transaction_workspace(
    staging_parent_fd: int,
    workspace_fd: int,
    workspace_name: str,
    workspace_info: os.stat_result,
    children: Mapping[str, os.stat_result],
) -> None:
    """Delete only the two exact held workspace children; retain on ambiguity."""

    _verify_workspace_children(workspace_fd, children)
    opened: list[tuple[str, int, os.stat_result]] = []
    try:
        for name, expected in children.items():
            child_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=workspace_fd,
            )
            observed = os.fstat(child_fd)
            if (observed.st_dev, observed.st_ino) != (expected.st_dev, expected.st_ino):
                os.close(child_fd)
                raise MaterializerError("transaction workspace child identity changed")
            opened.append((name, child_fd, expected))
        for name, child_fd, expected in opened:
            _clear_owned_tree(child_fd)
            named = os.stat(name, dir_fd=workspace_fd, follow_symlinks=False)
            if (named.st_dev, named.st_ino) != (expected.st_dev, expected.st_ino):
                raise MaterializerError("transaction workspace child identity changed")
            os.rmdir(name, dir_fd=workspace_fd)
        os.fsync(workspace_fd)
        named_root = os.stat(
            workspace_name,
            dir_fd=staging_parent_fd,
            follow_symlinks=False,
        )
        if (named_root.st_dev, named_root.st_ino) != (
            workspace_info.st_dev,
            workspace_info.st_ino,
        ):
            raise MaterializerError("transaction workspace root identity changed")
        os.rmdir(workspace_name, dir_fd=staging_parent_fd)
        os.fsync(staging_parent_fd)
    finally:
        for _name, descriptor, _expected in opened:
            os.close(descriptor)


def materialize_transaction(
    *,
    staging_parent: Path | None = None,
    source_root: Path = DEFAULT_SOURCE_ROOT,
    bootstrap_source: Path = DEFAULT_BOOTSTRAP_SOURCE,
    manifest_root: Path = DEFAULT_MANIFEST_ROOT,
    cpython_root: Path = DEFAULT_CPYTHON_ROOT,
    metis_root: Path = DEFAULT_METIS_ROOT,
    node_path: Path = DEFAULT_NODE_PATH,
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    semantic_registry_path: Path = DEFAULT_SEMANTIC_REGISTRY_PATH,
) -> dict[str, object]:
    """Build, validate and publish the bounded Phase-B outputs transactionally."""

    source_root = Path(source_root)
    bootstrap_source = Path(bootstrap_source)
    manifest_root = Path(manifest_root)
    staging_parent = Path(staging_parent) if staging_parent is not None else source_root.parent
    for label, path in (
        ("source root", source_root),
        ("bootstrap source", bootstrap_source),
        ("manifest root", manifest_root),
        ("staging parent", staging_parent),
    ):
        if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts[1:]):
            raise MaterializerError(f"transaction {label} path invalid")

    (
        source_fd,
        manifest_fd,
        staging_parent_fd,
        source_initial,
        manifest_initial,
        wheels_before,
        workspace_fd,
        workspace_info,
        workspace_name,
    ) = _prepare_transaction_context(source_root, manifest_root, staging_parent)
    workspace_path = staging_parent / workspace_name
    bootstrap_fd = -1
    bootstrap_parent_fd = -1
    bootstrap_parent_info: os.stat_result | None = None
    bootstrap_root_initial: os.stat_result | None = None
    bootstrap_parent_name = ""
    staging_source_fd = -1
    publication_files_fd = -1
    created_source: list[tuple[str, os.stat_result]] = []
    manifest_owned: dict[str, tuple[int, int, str]] = {}
    bootstrap_owned: dict[str, tuple[int, int, str]] = {}
    workspace_publication_owned: dict[str, tuple[int, int, str]] = {}
    workspace_children: dict[str, os.stat_result] = {}
    source_states: dict[str, str] = {}
    source_infos: dict[str, os.stat_result] = {}
    output_states: dict[str, str] = {}
    output_infos: dict[str, os.stat_result] = {}
    bootstrap_state = ""
    bootstrap_info: os.stat_result | None = None
    result: dict[str, object] | None = None
    publication_started = False
    try:
        result = build_materialization(
            workspace_path / "source",
            cpython_root=Path(cpython_root),
            metis_root=Path(metis_root),
            node_path=Path(node_path),
            wheel_root=source_root / "wheels",
            candidates_path=Path(candidates_path),
            semantic_registry_path=Path(semantic_registry_path),
            _staging_parent_fd=workspace_fd,
        )
        staging_source_fd = os.open(
            "source",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=workspace_fd,
        )
        staging_source_info = os.fstat(staging_source_fd)
        named_staging_source = os.stat(
            "source",
            dir_fd=workspace_fd,
            follow_symlinks=False,
        )
        if _identity(staging_source_info) != _identity(named_staging_source):
            raise MaterializerError("staged source root identity changed")
        workspace_children["source"] = staging_source_info
        descriptor = installer.validate_bootstrap_descriptor_bytes(result["descriptor_payload"])
        descriptor_files = list(descriptor["files"])
        _verify_tree_at(
            staging_source_fd,
            descriptor_files,
            label="staged materialization",
        )
        if result["stage0_payload"] != verify_stage0_builds():
            raise MaterializerError("Stage0 payload changed before publication")
        output_payloads = {name: bytes(result[key]) for key, name in _MANIFEST_OUTPUT_NAMES.items()}
        publication_files_fd, publication_files_info = _mkdir_exclusive_at(
            workspace_fd,
            "publication-files",
        )
        workspace_children["publication-files"] = publication_files_info
        _write_relative_exclusive(
            publication_files_fd,
            bootstrap_source.name,
            bytes(result["stage0_payload"]),
            0o555,
            owned_entries=workspace_publication_owned,
        )
        for name, payload in output_payloads.items():
            _write_relative_exclusive(
                publication_files_fd,
                name,
                payload,
                0o644,
                owned_entries=workspace_publication_owned,
            )

        expected_by_child = {
            child: _child_expected_rows(descriptor_files, child)
            for child in _SOURCE_PUBLICATION_CHILDREN
        }
        for child, expected_rows in expected_by_child.items():
            try:
                os.stat(child, dir_fd=source_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            info = _verify_child_at(
                source_fd,
                child,
                expected_rows,
                label=f"adopted source child {child}",
            )
            source_states[child] = "adopted"
            source_infos[child] = info

        for name, payload in output_payloads.items():
            try:
                os.stat(name, dir_fd=manifest_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            measured, info = _read_regular_at(
                manifest_fd,
                name,
                label=f"adopted manifest output {name}",
                required_mode=0o644,
            )
            if measured != payload:
                raise MaterializerError(f"adopted manifest output {name} differs")
            output_states[name] = "adopted"
            output_infos[name] = info

        try:
            bootstrap_fd = _open_directory_no_follow(bootstrap_source.parent)
        except MaterializerError:
            try:
                os.stat(bootstrap_source.parent, follow_symlinks=False)
            except FileNotFoundError:
                (
                    bootstrap_parent_fd,
                    bootstrap_fd,
                    bootstrap_parent_name,
                    bootstrap_parent_info,
                ) = _mkdir_exclusive_open(bootstrap_source.parent)
            else:
                raise
        bootstrap_names = set(os.listdir(bootstrap_fd))
        if not bootstrap_names.issubset({bootstrap_source.name}):
            raise MaterializerError("bootstrap source root contains an unknown child")
        bootstrap_root_initial = os.fstat(bootstrap_fd)
        if bootstrap_source.name in bootstrap_names:
            measured, bootstrap_info = _read_regular_at(
                bootstrap_fd,
                bootstrap_source.name,
                label="adopted durable Stage0 source",
                required_mode=0o555,
            )
            if measured != result["stage0_payload"]:
                raise MaterializerError("adopted durable Stage0 source differs")
            bootstrap_state = "adopted"

        publication_started = True
        for child in _SOURCE_PUBLICATION_CHILDREN:
            if child in source_states:
                continue
            staged_info = _verify_child_at(
                staging_source_fd,
                child,
                expected_by_child[child],
                label=f"staged source child {child}",
            )

            def record_source_effect(
                bound: os.stat_result,
                *,
                source_child: str = child,
            ) -> None:
                created_source.append((source_child, bound))
                source_states[source_child] = "created"
                source_infos[source_child] = bound

            try:
                _rename_exclusive_recorded(
                    staging_source_fd,
                    child,
                    source_fd,
                    child,
                    staged_info,
                    kind="directory",
                    record_effect=record_source_effect,
                )
            except OSError as error:
                raise MaterializerError(
                    f"atomic source child {child} publication failed"
                ) from error
            os.fsync(staging_source_fd)
            os.fsync(source_fd)
            info = _verify_child_at(
                source_fd,
                child,
                expected_by_child[child],
                label=f"published source child {child}",
            )
            pinned_info = source_infos[child]
            if (info.st_dev, info.st_ino) != (pinned_info.st_dev, pinned_info.st_ino):
                raise MaterializerError(f"published source child {child} identity changed")

        if not bootstrap_state:
            bootstrap_state, bootstrap_info = _adopt_or_publish_file_at(
                bootstrap_fd,
                bootstrap_source.name,
                bytes(result["stage0_payload"]),
                0o555,
                label="durable Stage0 source",
                owned_entries=bootstrap_owned,
                staging_fd=publication_files_fd,
                staging_name=bootstrap_source.name,
            )
        for name, payload in output_payloads.items():
            if name in output_states:
                continue
            state, info = _adopt_or_publish_file_at(
                manifest_fd,
                name,
                payload,
                0o644,
                label=f"canonical manifest output {name}",
                owned_entries=manifest_owned,
                staging_fd=publication_files_fd,
                staging_name=name,
            )
            output_states[name] = state
            output_infos[name] = info

        observed_source = _verify_tree_at(
            source_fd,
            descriptor_files,
            label="published fixed source tree",
        )
        wheels_after = _measure_wheels_at(source_fd)
        if wheels_after != wheels_before:
            raise MaterializerError("fixed wheel identities changed during publication")
        for child in _SOURCE_PUBLICATION_CHILDREN:
            sealed_child = _verify_child_at(
                source_fd,
                child,
                expected_by_child[child],
                label=f"sealed source child {child}",
            )
            pinned_child = source_infos[child]
            if (sealed_child.st_dev, sealed_child.st_ino) != (
                pinned_child.st_dev,
                pinned_child.st_ino,
            ):
                raise MaterializerError(f"sealed source child {child} identity changed")
        _verify_owned_entries(manifest_fd, manifest_owned)
        _verify_owned_entries(bootstrap_fd, bootstrap_owned)
        for name, payload in output_payloads.items():
            measured, info = _read_regular_at(
                manifest_fd,
                name,
                label=f"sealed manifest output {name}",
                required_mode=0o644,
            )
            if measured != payload or _identity(info) != _identity(output_infos[name]):
                raise MaterializerError(f"sealed manifest output {name} identity changed")
        sealed_stage0, sealed_stage0_info = _read_regular_at(
            bootstrap_fd,
            bootstrap_source.name,
            label="sealed durable Stage0 source",
            required_mode=0o555,
        )
        if (
            bootstrap_info is None
            or sealed_stage0 != result["stage0_payload"]
            or _identity(sealed_stage0_info) != _identity(bootstrap_info)
        ):
            raise MaterializerError("sealed durable Stage0 source changed")
        current_source = os.fstat(source_fd)
        absolute_source = _validate_absolute_ancestry(source_root, expect_directory=True)
        current_manifest = os.fstat(manifest_fd)
        absolute_manifest = _validate_absolute_ancestry(manifest_root, expect_directory=True)
        current_bootstrap_root = os.fstat(bootstrap_fd)
        absolute_bootstrap_root = _validate_absolute_ancestry(
            bootstrap_source.parent,
            expect_directory=True,
        )
        if (
            (current_source.st_dev, current_source.st_ino)
            != (source_initial.st_dev, source_initial.st_ino)
            or _identity(absolute_source) != _identity(current_source)
            or (current_manifest.st_dev, current_manifest.st_ino)
            != (manifest_initial.st_dev, manifest_initial.st_ino)
            or _identity(absolute_manifest) != _identity(current_manifest)
            or bootstrap_root_initial is None
            or (current_bootstrap_root.st_dev, current_bootstrap_root.st_ino)
            != (bootstrap_root_initial.st_dev, bootstrap_root_initial.st_ino)
            or _identity(absolute_bootstrap_root) != _identity(current_bootstrap_root)
        ):
            raise MaterializerError("publication root identity changed")
        _verify_workspace_children(workspace_fd, workspace_children)

        source_outputs = []
        for child in _SOURCE_PUBLICATION_CHILDREN:
            rows = expected_by_child[child]
            source_outputs.append(
                {
                    "path": str(source_root / child),
                    "state": source_states[child],
                    "files": len(rows),
                    "bytes": sum(int(row["size"]) for row in rows),
                    "sha256": _rows_digest(rows),
                }
            )
        manifest_outputs = [
            {
                "path": str(manifest_root / name),
                "state": output_states[name],
                "size": len(payload),
                "sha256": _sha256(payload),
                "mode": "0644",
            }
            for name, payload in sorted(output_payloads.items())
        ]
        receipt: dict[str, object] = {
            "schema_version": 1,
            "kind": "w3-phase-b-materialization-receipt",
            "status": "sealed",
            "source_root": str(source_root),
            "source_outputs": source_outputs,
            "source_tree": {
                "files": len(observed_source),
                "bytes": sum(int(row["size"]) for row in observed_source),
                "sha256": _rows_digest(observed_source),
            },
            "bootstrap_source": {
                "path": str(bootstrap_source),
                "state": bootstrap_state,
                "size": len(result["stage0_payload"]),
                "sha256": _sha256(bytes(result["stage0_payload"])),
                "mode": "0555",
            },
            "manifest_outputs": manifest_outputs,
            "bundle_sha256": result["manifest"]["bundle_sha256"],
            "release_content_roster_sha256": result["manifest"]["release_content_roster_sha256"],
        }
        receipt["receipt_sha256"] = _sha256(
            json.dumps(
                receipt,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        )
        return receipt
    except BaseException as error:
        rollback_failures: list[str] = []
        if publication_started:
            try:
                _cleanup_owned_entries(manifest_fd, manifest_owned)
            except (OSError, MaterializerError):
                rollback_failures.append("manifest outputs")
            if bootstrap_fd >= 0:
                try:
                    _cleanup_owned_entries(bootstrap_fd, bootstrap_owned)
                except (OSError, MaterializerError):
                    rollback_failures.append("Stage0 source")
            if staging_source_fd >= 0:
                for child, expected in reversed(created_source):
                    try:
                        named = os.stat(child, dir_fd=source_fd, follow_symlinks=False)
                        if (named.st_dev, named.st_ino) != (expected.st_dev, expected.st_ino):
                            raise MaterializerError("published child identity changed")
                        _rename_exclusive(source_fd, child, staging_source_fd, child)
                        os.fsync(source_fd)
                        os.fsync(staging_source_fd)
                    except (OSError, MaterializerError):
                        rollback_failures.append(f"source child {child}")
        if bootstrap_parent_info is not None and bootstrap_parent_fd >= 0:
            try:
                named = os.stat(
                    bootstrap_parent_name,
                    dir_fd=bootstrap_parent_fd,
                    follow_symlinks=False,
                )
                if (named.st_dev, named.st_ino) != (
                    bootstrap_parent_info.st_dev,
                    bootstrap_parent_info.st_ino,
                ):
                    raise MaterializerError("bootstrap root identity changed")
                os.rmdir(bootstrap_parent_name, dir_fd=bootstrap_parent_fd)
                os.fsync(bootstrap_parent_fd)
            except (OSError, MaterializerError):
                rollback_failures.append("bootstrap source root")
        if rollback_failures:
            raise MaterializerError(
                "materialization failed and rollback was incomplete: "
                + ", ".join(rollback_failures)
            ) from error
        if isinstance(error, (MaterializerError, OSError)):
            raise
        raise MaterializerError("materialization transaction failed") from error
    finally:
        active_exception = sys.exc_info()[0] is not None
        if publication_files_fd >= 0:
            os.close(publication_files_fd)
        if staging_source_fd >= 0:
            os.close(staging_source_fd)
        if bootstrap_fd >= 0:
            os.close(bootstrap_fd)
        if bootstrap_parent_fd >= 0:
            os.close(bootstrap_parent_fd)
        try:
            _cleanup_transaction_workspace(
                staging_parent_fd,
                workspace_fd,
                workspace_name,
                workspace_info,
                workspace_children,
            )
        except (OSError, MaterializerError) as cleanup_error:
            if not active_exception:
                raise MaterializerError(
                    "transaction workspace cleanup was ambiguous"
                ) from cleanup_error
        os.close(workspace_fd)
        os.close(staging_parent_fd)
        os.close(manifest_fd)
        os.close(source_fd)


__all__ = [
    "DEFAULT_BOOTSTRAP_SOURCE",
    "DEFAULT_CANDIDATES_PATH",
    "DEFAULT_CAPSULE_EVIDENCE",
    "DEFAULT_CPYTHON_ROOT",
    "DEFAULT_MANIFEST_ROOT",
    "DEFAULT_METIS_ROOT",
    "DEFAULT_NODE_PATH",
    "DEFAULT_SEMANTIC_REGISTRY_PATH",
    "DEFAULT_SOURCE_ROOT",
    "DEFAULT_STAGE0_BUILD_A",
    "DEFAULT_STAGE0_BUILD_B",
    "DEFAULT_WHEEL_ROOT",
    "MaterializerError",
    "build_broker_config",
    "build_fixture_registry",
    "build_launchd_plists",
    "build_materialization",
    "build_native_binaries",
    "capture_cpython",
    "census_cpython",
    "census_node_capsule",
    "inspect_exact_wheels",
    "inspect_wheel",
    "is_forbidden_cpython_path",
    "materialize_transaction",
    "project_capsule_install",
    "project_cpython_install",
    "project_project_modules",
    "validate_global_install_paths",
    "verify_stage0_builds",
]
