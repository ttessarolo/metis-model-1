#!/usr/bin/env python3
"""One-shot, clean-process verifier for the bounded W3 qualification gate.

The launcher is intentionally standalone and standard-library only.  It never
imports the Model 1 package.  An independently supplied authority digest pins
the exact authority manifest, which in turn pins every byte copied into a
content-addressed bundle.  The bundled worker is untrusted: this launcher
reconstructs requests, roles, counts, semantic truth and every reported hash.

This file does not contain a production worker and cannot ratify semantic
truth.  Until an independent reviewer supplies an authority manifest for an
audited worker and registry, qualification is blocked before child creation.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
PROTOCOL = "w3-clean-process-v1"
QUALIFICATION_ID = "w3-f1-f3-clean-process-qualification-v1"
CLAIM = "three_candidate_infrastructure_only_no_accuracy_claim"
HASH_PREFIX = "sha256:"
MAX_AUTHORITY_BYTES = 1024 * 1024
MAX_BUNDLE_FILE_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_BYTES = 32 * 1024 * 1024
MAX_WORKER_INPUT_BYTES = 4 * 1024 * 1024
MAX_WORKER_STDOUT_BYTES = 8 * 1024 * 1024
MAX_WORKER_STDERR_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 1024 * 1024
MAX_PUBLISHED_BYTES = (5 * MAX_ARTIFACT_BYTES) + MAX_REPORT_BYTES
MAX_TIMEOUT_SECONDS = 60.0
PINNED_METIS_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
PINNED_METIS_TREE = "75473e26deff4084a0eb077a4c3e27d52dc07998"
PINNED_NODE_VERSION = "v22.22.3"
REQUIRED_LAUNCHER_FLAGS = ("-I", "-S", "-B")
SANDBOX_EXEC_PATH = Path("/usr/bin/sandbox-exec")
OUTER_SANDBOX_POLICY_TEMPLATE = """(version 1)
(deny default)
(deny network*)
(allow process-exec (literal (param "PYTHON_EXECUTABLE")))
(allow file-read*)
(deny file-read*
  (subpath "/Users")
  (subpath "/Volumes")
  (subpath "/Network")
  (subpath "/Applications")
  (subpath "/private/etc")
  (subpath "/private/tmp")
  (subpath "/private/var/folders")
  (subpath "/Library/Keychains")
  (subpath (param "SOURCE_ROOT"))
  (subpath (param "ARTIFACT_ROOT")))
(allow file-read*
  (subpath (param "PYTHON_ROOT"))
  (subpath (param "BUNDLE_ROOT"))
  (subpath (param "PROCESS_ROOT")))
(allow file-write* (subpath (param "PROCESS_ROOT")))
(allow sysctl-read)
(allow mach-lookup)
"""
OUTER_SANDBOX_POLICY_TEMPLATE_SHA256 = (
    HASH_PREFIX + hashlib.sha256(OUTER_SANDBOX_POLICY_TEMPLATE.encode("utf-8")).hexdigest()
)
CANDIDATE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SEMANTIC_FILENAME_PATTERN = re.compile(
    r"^(?:[A-Za-z0-9][A-Za-z0-9._-]*/)*"
    r"[A-Za-z0-9][A-Za-z0-9._-]*\.metis$"
)
ARTIFACT_PATH_PATTERN = re.compile(
    r"^artifacts/(?:[A-Za-z0-9][A-Za-z0-9._-]*/)*"
    r"[A-Za-z0-9][A-Za-z0-9._-]*\.json$"
)
QUALIFICATION_STOPS = [
    "no_production_worker_or_runner_execution",
    "stdlib_import_closure_not_materialized_or_content_addressed",
    "no_w1_slice_or_dataset_promotion",
    "no_f4_f5_f6_claim",
    "no_semantic_accuracy_claim",
]

EXPECTED_ROLE_COUNTS = {
    "author": 1,
    "before": 1,
    "after": 1,
    "mutated": 1,
    "fixed": 1,
}
ROLE_CONTRACT = {
    "F-1": (("author", "target_source", "ok"),),
    "F-2": (("before", "before_source", "ok"), ("after", "after_source", "ok")),
    "F-3": (("mutated", "mutated_source", "invalid"), ("fixed", "fixed_source", "ok")),
}
REQUIRED_BUNDLE_KINDS = frozenset({"w3", "schema", "manifest", "runner", "worker"})
EVIDENCE_PIN_KEYS = frozenset(
    {
        "runner_sha256",
        "tooling_package_sha256",
        "tooling_lock_sha256",
        "node_modules_sha256",
        "node_binary_sha256",
        "sandbox_policy_sha256",
        "metis_status_sha256",
    }
)
RUNTIME_IDENTITY_KEYS = frozenset(
    {
        "node",
        "node_path",
        "tsx_path",
        "runner_path",
        "snapshot_revision",
        "snapshot_tree",
        "tooling_package_sha256",
        "tooling_lock_sha256",
        "node_modules_sha256",
        "node_binary_sha256",
        "sandbox_exec_path",
        "sandbox_policy_version",
        "sandbox_policy_sha256",
    }
)
LAUNCHER_IDENTITY_KEYS = frozenset(
    {
        "qualifier_path",
        "qualifier_sha256",
        "python_executable",
        "python_executable_sha256",
        "python_version",
        "required_flags",
        "sandbox_exec_path",
        "sandbox_exec_sha256",
        "sandbox_policy_template_sha256",
    }
)
EVIDENCE_KEYS = frozenset(
    {
        "input_sha256",
        "diagnostics_sha256",
        "ast_sha256",
        "ir_sha256",
        "toolchain_revision",
        "toolchain_tree",
        "runtime_sha256",
        "runtime_identity",
        "runner_sha256",
        "tooling_package_sha256",
        "tooling_lock_sha256",
        "node_modules_sha256",
        "node_binary_sha256",
        "sandbox_policy_sha256",
        "metis_status_sha256",
        "metis_status",
        "envelope_sha256",
    }
)
RESULT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "endpoint",
        "diagnostics",
        "ast",
        "ir",
        "toolchain",
        "runtime",
        "failure",
    }
)


class QualificationBlocked(ValueError):
    """The bounded qualification cannot produce an authoritative green."""


def canonical_json_bytes(value: Any) -> bytes:
    """Encode exact deterministic JSON and reject non-finite numbers."""

    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise QualificationBlocked(f"value is not canonical JSON: {error}") from error
    return rendered.encode("utf-8")


def canonical_hash(value: Any) -> str:
    return HASH_PREFIX + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return HASH_PREFIX + hashlib.sha256(value).hexdigest()


def _valid_hash(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith(HASH_PREFIX):
        return False
    digest = value[len(HASH_PREFIX) :]
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def _exact_int(value: Any, expected: int, label: str) -> None:
    if type(value) is not int or value != expected:
        raise QualificationBlocked(f"{label} must be the exact integer {expected}")


def _require_launcher_flags() -> None:
    if not (
        sys.flags.isolated == 1 and sys.flags.no_site == 1 and sys.flags.dont_write_bytecode == 1
    ):
        raise QualificationBlocked("launcher requires exact isolated flags -I -S -B")


def _launcher_identity() -> dict[str, Any]:
    try:
        qualifier = Path(__file__).resolve(strict=True)
        python = Path(sys.executable).resolve(strict=True)
        sandbox = SANDBOX_EXEC_PATH.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise QualificationBlocked("launcher executable identity is unavailable") from error
    if qualifier.is_symlink() or python.is_symlink() or sandbox.is_symlink():
        raise QualificationBlocked("launcher executable identity may not be a symlink")
    qualifier_bytes = _read_regular_file(qualifier, MAX_BUNDLE_FILE_BYTES, "qualifier")
    python_bytes = _read_regular_file(python, MAX_BUNDLE_FILE_BYTES, "Python executable")
    sandbox_bytes = _read_regular_file(sandbox, MAX_BUNDLE_FILE_BYTES, "sandbox-exec")
    version = sys.version_info
    python_version = f"{version.major}.{version.minor}.{version.micro}"
    return {
        "qualifier_path": str(qualifier),
        "qualifier_sha256": _bytes_hash(qualifier_bytes),
        "python_executable": str(python),
        "python_executable_sha256": _bytes_hash(python_bytes),
        "python_version": python_version,
        "required_flags": list(REQUIRED_LAUNCHER_FLAGS),
        "sandbox_exec_path": str(sandbox),
        "sandbox_exec_sha256": _bytes_hash(sandbox_bytes),
        "sandbox_policy_template_sha256": OUTER_SANDBOX_POLICY_TEMPLATE_SHA256,
    }


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationBlocked(f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise QualificationBlocked(f"JSON contains non-finite constant {value}")


def _decode_json(raw: bytes, label: str, *, require_canonical: bool = False) -> Any:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise QualificationBlocked(f"{label} is not valid JSON: {error}") from error
    if require_canonical and raw != canonical_json_bytes(value):
        raise QualificationBlocked(f"{label} is not canonical JSON")
    return value


def _exact_keys(value: Any, keys: set[str] | frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise QualificationBlocked(f"{label} does not have the exact registered fields")
    return value


def _safe_relative_path(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise QualificationBlocked(f"{label} is not a safe relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise QualificationBlocked(f"{label} is not a safe relative POSIX path")
    return path


def _read_regular_file(path: Path, limit: int, label: str) -> bytes:
    try:
        before = path.lstat()
    except OSError as error:
        raise QualificationBlocked(f"{label} is unavailable") from error
    if path.is_symlink() or not path.is_file():
        raise QualificationBlocked(f"{label} must be a regular non-symlink file")
    if before.st_size > limit:
        raise QualificationBlocked(f"{label} exceeds its size cap")
    try:
        raw = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise QualificationBlocked(f"{label} cannot be read") from error
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_mode,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_mode,
    )
    if identity_before != identity_after or len(raw) != before.st_size:
        raise QualificationBlocked(f"{label} changed while it was read")
    return raw


def _source_file(root: Path, relative: PurePosixPath, label: str) -> Path:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise QualificationBlocked(f"{label} crosses a symlink")
    try:
        resolved = current.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise QualificationBlocked(f"{label} is unavailable") from error
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise QualificationBlocked(f"{label} escapes the source root") from error
    return resolved


def _manifest_hash(value: Any, field: str = "manifest_sha256") -> str:
    if not isinstance(value, dict) or field not in value:
        raise QualificationBlocked("manifest is missing its digest")
    body = {key: item for key, item in value.items() if key != field}
    measured = canonical_hash(body)
    if value[field] != measured:
        raise QualificationBlocked("manifest digest does not match its exact content")
    return measured


def _load_authority(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not _valid_hash(expected_sha256):
        raise QualificationBlocked("an external authority digest is required")
    raw = _read_regular_file(path, MAX_AUTHORITY_BYTES, "authority manifest")
    authority = _decode_json(raw, "authority manifest", require_canonical=True)
    keys = {
        "schema_version",
        "authority_id",
        "status",
        "semantic_registry",
        "candidate_manifest",
        "worker",
        "launcher",
        "toolchain",
        "runtime_identity",
        "evidence_pins",
        "bundle_files",
        "expected",
        "manifest_sha256",
    }
    authority = _exact_keys(authority, keys, "authority manifest")
    _exact_int(authority["schema_version"], SCHEMA_VERSION, "authority schema version")
    if not isinstance(authority["authority_id"], str) or not authority["authority_id"]:
        raise QualificationBlocked("authority id is missing")
    if authority["status"] != "independently_ratified":
        raise QualificationBlocked("authority manifest is not independently ratified")
    measured = _manifest_hash(authority)
    if measured != expected_sha256:
        raise QualificationBlocked("authority manifest differs from the external digest")

    semantic = _exact_keys(
        authority["semantic_registry"],
        {"path", "manifest_sha256", "ratification"},
        "semantic registry authority",
    )
    _safe_relative_path(semantic["path"], "semantic registry path")
    if not _valid_hash(semantic["manifest_sha256"]):
        raise QualificationBlocked("semantic registry digest is invalid")
    ratification = _exact_keys(
        semantic["ratification"],
        {"status", "author_id", "ratifier_id", "independent", "evidence_sha256"},
        "semantic registry ratification",
    )
    if (
        ratification["status"] != "independently_ratified"
        or ratification["independent"] is not True
        or not isinstance(ratification["author_id"], str)
        or not ratification["author_id"]
        or not isinstance(ratification["ratifier_id"], str)
        or not ratification["ratifier_id"]
        or ratification["author_id"] == ratification["ratifier_id"]
        or not _valid_hash(ratification["evidence_sha256"])
    ):
        raise QualificationBlocked("semantic registry lacks independent ratification")

    candidate = _exact_keys(
        authority["candidate_manifest"],
        {"path", "manifest_sha256"},
        "candidate manifest authority",
    )
    _safe_relative_path(candidate["path"], "candidate manifest path")
    if not _valid_hash(candidate["manifest_sha256"]):
        raise QualificationBlocked("candidate manifest digest is invalid")

    worker = _exact_keys(authority["worker"], {"path", "protocol"}, "worker authority")
    _safe_relative_path(worker["path"], "worker path")
    if worker["protocol"] != PROTOCOL:
        raise QualificationBlocked("worker protocol is not registered")

    launcher = _exact_keys(authority["launcher"], LAUNCHER_IDENTITY_KEYS, "launcher authority")
    if launcher != _launcher_identity():
        raise QualificationBlocked("launcher identity differs from external authority")

    toolchain = _exact_keys(
        authority["toolchain"], {"revision", "tree", "language_version"}, "toolchain"
    )
    if toolchain != {
        "revision": PINNED_METIS_REVISION,
        "tree": PINNED_METIS_TREE,
        "language_version": "0.43",
    }:
        raise QualificationBlocked("toolchain authority is invalid")
    runtime = _exact_keys(
        authority["runtime_identity"], RUNTIME_IDENTITY_KEYS, "runtime identity authority"
    )
    pins = _exact_keys(authority["evidence_pins"], EVIDENCE_PIN_KEYS, "evidence pins")
    if any(not _valid_hash(value) for value in pins.values()):
        raise QualificationBlocked("evidence pin is invalid")
    expected_runtime_values = {
        "node": PINNED_NODE_VERSION,
        "snapshot_revision": PINNED_METIS_REVISION,
        "snapshot_tree": PINNED_METIS_TREE,
        "tooling_package_sha256": pins["tooling_package_sha256"],
        "tooling_lock_sha256": pins["tooling_lock_sha256"],
        "node_modules_sha256": pins["node_modules_sha256"],
        "node_binary_sha256": pins["node_binary_sha256"],
        "sandbox_exec_path": "sandbox-exec:///usr/bin/sandbox-exec",
        "sandbox_policy_version": "2",
        "sandbox_policy_sha256": pins["sandbox_policy_sha256"],
    }
    if any(runtime[key] != value for key, value in expected_runtime_values.items()):
        raise QualificationBlocked("runtime identity differs from its transitive pins")
    snapshot = f"snapshot://{PINNED_METIS_REVISION}/{PINNED_METIS_TREE}"
    if (
        runtime["node_path"] != f"node://{PINNED_NODE_VERSION}"
        or runtime["tsx_path"] != f"{snapshot}/tooling/node_modules/tsx/dist/loader.mjs"
        or runtime["runner_path"] != f"{snapshot}/.metis-oracle/runner.ts"
    ):
        raise QualificationBlocked("runtime executable identities differ from the snapshot")

    expected = _exact_keys(
        authority["expected"],
        {"candidates", "executions", "roles"},
        "expected roster",
    )
    _exact_int(expected["candidates"], 3, "expected candidate count")
    _exact_int(expected["executions"], 5, "expected execution count")
    if expected["roles"] != EXPECTED_ROLE_COUNTS or any(
        type(value) is not int for value in expected["roles"].values()
    ):
        raise QualificationBlocked("authority does not describe the exact three-candidate gate")
    return authority


def _read_bundle_sources(
    authority: dict[str, Any], source_root: Path
) -> tuple[list[dict[str, str]], dict[str, bytes]]:
    records = authority["bundle_files"]
    if not isinstance(records, list) or not records or len(records) > 128:
        raise QualificationBlocked("bundle file roster is empty or exceeds its cap")
    material: list[dict[str, str]] = []
    contents: dict[str, bytes] = {}
    kinds: Counter[str] = Counter()
    total = 0
    for index, item in enumerate(records):
        item = _exact_keys(item, {"path", "kind", "file_sha256"}, f"bundle file {index}")
        relative = _safe_relative_path(item["path"], f"bundle file {index} path")
        kind = item["kind"]
        if kind not in REQUIRED_BUNDLE_KINDS or not _valid_hash(item["file_sha256"]):
            raise QualificationBlocked(f"bundle file {index} authority is invalid")
        name = relative.as_posix()
        if name in contents:
            raise QualificationBlocked("bundle paths are not unique")
        raw = _read_regular_file(
            _source_file(source_root, relative, f"bundle file {name}"),
            MAX_BUNDLE_FILE_BYTES,
            f"bundle file {name}",
        )
        total += len(raw)
        if total > MAX_BUNDLE_BYTES:
            raise QualificationBlocked("bundle exceeds its aggregate size cap")
        if _bytes_hash(raw) != item["file_sha256"]:
            raise QualificationBlocked(f"bundle file {name} differs from its authority")
        contents[name] = raw
        kinds[kind] += 1
        material.append({"path": name, "kind": kind, "file_sha256": item["file_sha256"]})
    if not REQUIRED_BUNDLE_KINDS.issubset(kinds):
        raise QualificationBlocked("bundle omits a required W3/schema/manifest/runner/worker kind")
    if kinds["worker"] != 1 or kinds["runner"] != 1:
        raise QualificationBlocked("bundle must contain exactly one worker and one runner")
    by_path = {item["path"]: item for item in material}
    required_paths = {
        authority["worker"]["path"]: "worker",
        authority["semantic_registry"]["path"]: "manifest",
        authority["candidate_manifest"]["path"]: "manifest",
    }
    if any(by_path.get(path, {}).get("kind") != kind for path, kind in required_paths.items()):
        raise QualificationBlocked("authority paths are not bound into the bundle roster")
    runner_record = next(item for item in material if item["kind"] == "runner")
    if authority["evidence_pins"]["runner_sha256"] != runner_record["file_sha256"]:
        raise QualificationBlocked("runner evidence pin differs from bundled runner bytes")
    return sorted(material, key=lambda item: item["path"]), contents


def _make_writable(path: Path) -> None:
    if not path.exists():
        return
    for item in sorted(path.rglob("*"), key=lambda value: len(value.parts), reverse=True):
        with contextlib.suppress(OSError):
            item.chmod(0o700 if item.is_dir() else 0o600)
    with contextlib.suppress(OSError):
        path.chmod(0o700)


def _remove_tree(path: Path) -> None:
    _make_writable(path)
    shutil.rmtree(path, ignore_errors=True)


def _verify_materialized_bundle(
    bundle: Path,
    bundle_body: dict[str, Any],
    contents: dict[str, bytes],
    *,
    immutable: bool = True,
) -> None:
    if bundle.is_symlink() or not bundle.is_dir():
        raise QualificationBlocked("materialized bundle root is not a regular directory")
    expected_files = set(contents) | {"bundle.json"}
    actual_files = {
        item.relative_to(bundle).as_posix() for item in bundle.rglob("*") if item.is_file()
    }
    actual_items = list(bundle.rglob("*"))
    expected_directories = {
        PurePosixPath(name).parent.as_posix()
        for name in expected_files
        if PurePosixPath(name).parent.as_posix() != "."
    }
    expected_directories |= {
        parent.as_posix()
        for name in tuple(expected_directories)
        for parent in PurePosixPath(name).parents
        if parent.as_posix() != "."
    }
    actual_directories = {
        item.relative_to(bundle).as_posix() for item in actual_items if item.is_dir()
    }
    if (
        actual_files != expected_files
        or actual_directories != expected_directories
        or any(item.is_symlink() for item in actual_items)
    ):
        raise QualificationBlocked("materialized bundle roster changed")
    if immutable:
        if stat.S_IMODE(bundle.lstat().st_mode) != 0o555:
            raise QualificationBlocked("materialized bundle root mode changed")
        if any(
            stat.S_IMODE(item.lstat().st_mode) != 0o555 for item in actual_items if item.is_dir()
        ):
            raise QualificationBlocked("materialized bundle directory mode changed")
        if any(
            stat.S_IMODE(item.lstat().st_mode) != 0o444 for item in actual_items if item.is_file()
        ):
            raise QualificationBlocked("materialized bundle file mode changed")
    metadata = _read_regular_file(bundle / "bundle.json", MAX_AUTHORITY_BYTES, "bundle metadata")
    if metadata != canonical_json_bytes(bundle_body):
        raise QualificationBlocked("materialized bundle metadata changed")
    for name, expected in contents.items():
        raw = _read_regular_file(bundle / name, MAX_BUNDLE_FILE_BYTES, f"bundled file {name}")
        if raw != expected:
            raise QualificationBlocked(f"bundled file {name} changed")


def _materialize_bundle(
    artifact_root: Path,
    authority_sha256: str,
    material: list[dict[str, str]],
    contents: dict[str, bytes],
) -> tuple[Path, str, dict[str, Any]]:
    bundle_core = {
        "schema_version": SCHEMA_VERSION,
        "authority_manifest_sha256": authority_sha256,
        "files": material,
    }
    bundle_sha256 = canonical_hash(bundle_core)
    bundle_body = {**bundle_core, "bundle_sha256": bundle_sha256}
    bundles_root = artifact_root / "bundles"
    if bundles_root.is_symlink():
        raise QualificationBlocked("bundle namespace may not be a symlink")
    bundles_root.mkdir(parents=True, exist_ok=True)
    if (
        bundles_root.is_symlink()
        or not bundles_root.is_dir()
        or bundles_root.resolve(strict=True) != artifact_root.resolve(strict=True) / "bundles"
    ):
        raise QualificationBlocked("bundle namespace is invalid")
    target = bundles_root / bundle_sha256[len(HASH_PREFIX) :]
    if target.exists():
        _verify_materialized_bundle(target, bundle_body, contents)
        return target, bundle_sha256, bundle_body
    temporary = Path(tempfile.mkdtemp(prefix=".w3-bundle-", dir=bundles_root))
    try:
        for name, raw in contents.items():
            destination = temporary / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
        (temporary / "bundle.json").write_bytes(canonical_json_bytes(bundle_body))
        _verify_materialized_bundle(temporary, bundle_body, contents, immutable=False)
        try:
            temporary.rename(target)
        except FileExistsError:
            _verify_materialized_bundle(target, bundle_body, contents)
            _remove_tree(temporary)
        for item in sorted(target.rglob("*"), key=lambda value: len(value.parts), reverse=True):
            item.chmod(0o555 if item.is_dir() else 0o444)
        target.chmod(0o555)
        _verify_materialized_bundle(target, bundle_body, contents)
        return target, bundle_sha256, bundle_body
    except Exception:
        _remove_tree(temporary)
        raise


def _canonical_workspace(value: Any, filename: str) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        raise QualificationBlocked("semantic workspace_sources is not an object")
    result: list[dict[str, str]] = []
    for name, source in sorted(value.items()):
        relative = _safe_relative_path(name, "workspace source")
        if (
            SEMANTIC_FILENAME_PATTERN.fullmatch(name) is None
            or name == filename
            or not isinstance(source, str)
            or not source
            or relative.as_posix() != name
        ):
            raise QualificationBlocked("workspace source is invalid")
        result.append({"filename": name, "source": source})
    return result


def _candidate_content(candidate: dict[str, Any]) -> dict[str, Any]:
    family = candidate.get("family")
    if family == "F-1":
        fields = ("request", "target_source")
    elif family == "F-2":
        fields = ("before_source", "after_source", "expected_delta")
    elif family == "F-3":
        fields = ("mutated_source", "expected_diagnostic", "fixed_source", "mutation_spec")
    else:
        raise QualificationBlocked("candidate family is not supported")
    if any(field not in candidate for field in fields):
        raise QualificationBlocked("candidate content is incomplete")
    return {field: candidate[field] for field in fields}


def _exact_count_map(value: Any, expected: dict[str, int], label: str) -> None:
    value = _exact_keys(value, set(expected), label)
    for key, count in expected.items():
        _exact_int(value[key], count, f"{label} {key}")


def _validate_diagnostics(
    value: Any, label: str, *, expected_filename: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    diagnostics = _exact_keys(value, {"parser", "link", "validation", "all"}, label)
    for channel, rows in diagnostics.items():
        if not isinstance(rows, list):
            raise QualificationBlocked(f"{label} {channel} is not a diagnostic list")
        for index, row in enumerate(rows):
            row = _exact_keys(
                row,
                {"filename", "message", "severity", "code", "range"},
                f"{label} {channel} diagnostic {index}",
            )
            filename = row["filename"]
            severity = row["severity"]
            code = row["code"]
            if (
                not isinstance(filename, str)
                or SEMANTIC_FILENAME_PATTERN.fullmatch(filename) is None
                or _safe_relative_path(filename, "diagnostic filename").as_posix() != filename
                or (expected_filename is not None and filename != expected_filename)
                or not isinstance(row["message"], str)
                or (severity is not None and type(severity) is not int)
                or (code is not None and type(code) not in {str, int})
            ):
                raise QualificationBlocked(f"{label} contains a malformed diagnostic")
    return diagnostics


def _validate_failure(value: Any, label: str) -> dict[str, str]:
    failure = _exact_keys(value, {"kind", "message"}, label)
    if (
        not isinstance(failure["kind"], str)
        or not failure["kind"]
        or not isinstance(failure["message"], str)
    ):
        raise QualificationBlocked(f"{label} is malformed")
    return failure


def _validate_registered_semantic_endpoint(family: str, semantic_spec: dict[str, Any]) -> None:
    semantic_spec = _exact_keys(
        semantic_spec,
        {
            "schema_version",
            "contract",
            "filename",
            "execution_mode",
            "endpoint",
            "workspace_sources",
            "truth",
            "provenance",
        },
        "semantic specification",
    )
    _exact_int(semantic_spec.get("schema_version"), 1, "semantic spec schema version")
    if semantic_spec.get("execution_mode") != "endpoint":
        raise QualificationBlocked("bounded qualification supports endpoint mode only")
    endpoint = semantic_spec.get("endpoint")
    truth = semantic_spec.get("truth")
    if (
        not isinstance(endpoint, str)
        or not endpoint
        or not isinstance(truth, dict)
        or truth.get("expected_endpoint") != endpoint
    ):
        raise QualificationBlocked("semantic endpoint differs from registered truth")
    provenance = _exact_keys(
        semantic_spec.get("provenance"),
        {"author", "method", "review_status"},
        "semantic provenance",
    )
    if (
        not isinstance(provenance["author"], str)
        or not provenance["author"]
        or provenance["method"] != "manual_contract_review"
        or provenance["review_status"] != "candidate_for_independent_review"
    ):
        raise QualificationBlocked("semantic provenance is invalid")
    if family == "F-1":
        if semantic_spec["contract"] != "F-1-author":
            raise QualificationBlocked("semantic family contract is invalid")
        truth = _exact_keys(
            truth,
            {
                "request_exact",
                "required_source_fragments",
                "expected_endpoint",
                "expected_ir",
            },
            "F-1 semantic truth",
        )
        fragments = truth["required_source_fragments"]
        if (
            not isinstance(truth["request_exact"], str)
            or not truth["request_exact"]
            or not isinstance(fragments, list)
            or not fragments
            or any(not isinstance(item, str) or not item for item in fragments)
            or len(set(fragments)) != len(fragments)
        ):
            raise QualificationBlocked("F-1 semantic truth is invalid")
        registered_irs = (truth.get("expected_ir"),)
    elif family == "F-2":
        if semantic_spec["contract"] != "F-2-minimal-edit":
            raise QualificationBlocked("semantic family contract is invalid")
        truth = _exact_keys(
            truth,
            {
                "old_text",
                "new_text",
                "occurrences",
                "expected_endpoint",
                "expected_before_ir",
                "expected_after_ir",
                "expected_changed_paths",
            },
            "F-2 semantic truth",
        )
        _exact_int(truth["occurrences"], 1, "F-2 occurrence count")
        if (
            not isinstance(truth["old_text"], str)
            or not truth["old_text"]
            or not isinstance(truth["new_text"], str)
            or not truth["new_text"]
            or truth["old_text"] == truth["new_text"]
            or truth["expected_changed_paths"] != ["variants[0].takes[0].count.take"]
        ):
            raise QualificationBlocked("F-2 semantic truth is invalid")
        registered_irs = (truth.get("expected_before_ir"), truth.get("expected_after_ir"))
    elif family == "F-3":
        if semantic_spec["contract"] != "F-3-diagnostic-repair":
            raise QualificationBlocked("semantic family contract is invalid")
        truth = _exact_keys(
            truth,
            {
                "expected_failure_kind",
                "expected_diagnostic_present",
                "expected_endpoint",
                "repair_fragment",
                "expected_failure",
                "expected_diagnostics",
                "expected_fixed_ir",
            },
            "F-3 semantic truth",
        )
        expected_failure = _validate_failure(truth["expected_failure"], "F-3 expected failure")
        expected_diagnostics = _validate_diagnostics(
            truth["expected_diagnostics"],
            "F-3 expected diagnostics",
            expected_filename=semantic_spec["filename"],
        )
        failure_channel = {
            "parse": "parser",
            "link": "link",
            "validation": "validation",
        }.get(truth["expected_failure_kind"])
        if (
            failure_channel is None
            or truth["expected_diagnostic_present"] is not True
            or not isinstance(truth["repair_fragment"], str)
            or not truth["repair_fragment"]
            or expected_failure["kind"] != truth["expected_failure_kind"]
            or not expected_diagnostics[failure_channel]
            or not expected_diagnostics["all"]
        ):
            raise QualificationBlocked("F-3 semantic truth is invalid")
        registered_irs = (truth.get("expected_fixed_ir"),)
    else:
        raise QualificationBlocked("candidate family is not supported")
    if any(not isinstance(ir, dict) or ir.get("name") != endpoint for ir in registered_irs):
        raise QualificationBlocked("registered IR endpoint name differs from semantic endpoint")


def _load_gate_inputs(
    authority: dict[str, Any], contents: dict[str, bytes]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    candidate_path = authority["candidate_manifest"]["path"]
    registry_path = authority["semantic_registry"]["path"]
    candidates = _decode_json(contents[candidate_path], "candidate manifest")
    registry = _decode_json(contents[registry_path], "semantic registry")
    if _manifest_hash(candidates) != authority["candidate_manifest"]["manifest_sha256"]:
        raise QualificationBlocked("candidate manifest differs from authority")
    if _manifest_hash(registry) != authority["semantic_registry"]["manifest_sha256"]:
        raise QualificationBlocked("semantic registry differs from authority")
    candidates = _exact_keys(
        candidates,
        {
            "schema_version",
            "manifest_id",
            "status",
            "claim",
            "counts",
            "candidates",
            "manifest_sha256",
        },
        "candidate manifest",
    )
    registry = _exact_keys(
        registry,
        {"schema_version", "registry_id", "review_status", "counts", "specs", "manifest_sha256"},
        "semantic registry",
    )
    _exact_int(candidates["schema_version"], 1, "candidate manifest schema version")
    _exact_int(registry["schema_version"], 1, "semantic registry schema version")
    if (
        candidates["manifest_id"] != "w3-f1-f3-smoke-candidates-v1"
        or candidates["claim"] != "no_accuracy_claim"
        or registry["registry_id"] != "w3-f1-f3-smoke-semantic-specs-v1"
    ):
        raise QualificationBlocked("candidate or semantic manifest identity is invalid")
    candidate_rows = candidates.get("candidates") if isinstance(candidates, dict) else None
    specs = registry.get("specs") if isinstance(registry, dict) else None
    if not isinstance(candidate_rows, list) or not isinstance(specs, list):
        raise QualificationBlocked("candidate or semantic roster is missing")
    if len(candidate_rows) != 3 or len(specs) != 3:
        raise QualificationBlocked("candidate and semantic rosters must contain exactly three rows")
    expected_manifest_counts = {"in": 3, "out": 3, "distinct": 3, "gaps": 0}
    _exact_count_map(candidates.get("counts"), expected_manifest_counts, "candidate counts")
    _exact_count_map(registry.get("counts"), expected_manifest_counts, "semantic counts")
    if (
        candidates.get("status") != "proposed_for_independent_review"
        or registry.get("review_status") != "candidate_for_independent_review"
    ):
        raise QualificationBlocked("candidate or semantic manifest overstates its review state")
    candidates_by_id: dict[str, dict[str, Any]] = {}
    specs_by_id: dict[str, dict[str, Any]] = {}
    for candidate in candidate_rows:
        if (
            not isinstance(candidate, dict)
            or not isinstance(candidate.get("candidate_id"), str)
            or CANDIDATE_ID_PATTERN.fullmatch(candidate["candidate_id"]) is None
        ):
            raise QualificationBlocked("candidate roster contains an invalid row")
        if candidate["candidate_id"] in candidates_by_id:
            raise QualificationBlocked("candidate ids are not unique")
        candidates_by_id[candidate["candidate_id"]] = candidate
    for spec in specs:
        if (
            not isinstance(spec, dict)
            or not isinstance(spec.get("candidate_id"), str)
            or CANDIDATE_ID_PATTERN.fullmatch(spec["candidate_id"]) is None
        ):
            raise QualificationBlocked("semantic roster contains an invalid row")
        if spec["candidate_id"] in specs_by_id:
            raise QualificationBlocked("semantic ids are not unique")
        specs_by_id[spec["candidate_id"]] = spec
    if set(candidates_by_id) != set(specs_by_id):
        raise QualificationBlocked("candidate and semantic rosters differ")
    if {item.get("family") for item in candidate_rows} != set(ROLE_CONTRACT):
        raise QualificationBlocked("candidate roster does not cover F-1/F-2/F-3 exactly")

    executions: list[dict[str, Any]] = []
    for candidate_id in sorted(candidates_by_id):
        candidate = candidates_by_id[candidate_id]
        spec = specs_by_id[candidate_id]
        semantic_spec = spec.get("semantic_spec")
        spec_body = {key: item for key, item in spec.items() if key != "spec_sha256"}
        if (
            spec.get("family") != candidate.get("family")
            or spec.get("spec_sha256") != canonical_hash(spec_body)
            or spec.get("content_sha256") != canonical_hash(_candidate_content(candidate))
            or candidate.get("root_evidence", {}).get("content_sha256")
            != spec.get("content_sha256")
            or spec.get("semantic_spec_sha256") != canonical_hash(semantic_spec)
            or candidate.get("semantic_spec") != semantic_spec
            or candidate.get("root_evidence", {}).get("semantic_spec_sha256")
            != spec.get("semantic_spec_sha256")
        ):
            raise QualificationBlocked("candidate is not bound to its registered exact content")
        if not isinstance(semantic_spec, dict):
            raise QualificationBlocked("semantic specification is missing")
        _validate_registered_semantic_endpoint(candidate["family"], semantic_spec)
        filename = semantic_spec.get("filename")
        mode = semantic_spec.get("execution_mode")
        endpoint = semantic_spec.get("endpoint")
        if (
            not isinstance(filename, str)
            or SEMANTIC_FILENAME_PATTERN.fullmatch(filename) is None
            or _safe_relative_path(filename, "semantic filename").as_posix() != filename
            or mode != "endpoint"
            or not isinstance(endpoint, str)
            or not endpoint
        ):
            raise QualificationBlocked("semantic execution contract is invalid")
        workspace = _canonical_workspace(semantic_spec.get("workspace_sources"), filename)
        for role, source_field, expected_status in ROLE_CONTRACT[candidate["family"]]:
            source = candidate.get(source_field)
            if not isinstance(source, str) or not source:
                raise QualificationBlocked("candidate role source is missing")
            request = {
                "schema_version": 1,
                "source": source,
                "filename": filename,
                "execution_mode": mode,
                "endpoint": endpoint,
                "metis_root": (
                    f"snapshot://{authority['toolchain']['revision']}/"
                    f"{authority['toolchain']['tree']}"
                ),
                "metis_revision": authority["toolchain"]["revision"],
                "metis_tree": authority["toolchain"]["tree"],
                "workspace_sources": workspace,
            }
            executions.append(
                {
                    "candidate_id": candidate_id,
                    "family": candidate["family"],
                    "role": role,
                    "expected_status": expected_status,
                    "request": request,
                }
            )
    if len(executions) != 5:
        raise QualificationBlocked("derived execution roster is not exact")
    return candidates_by_id, specs_by_id, executions


def _worker_input(
    authority: dict[str, Any],
    authority_sha256: str,
    bundle_sha256: str,
    executions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL,
        "authority_manifest_sha256": authority_sha256,
        "bundle_sha256": bundle_sha256,
        "candidate_manifest_sha256": authority["candidate_manifest"]["manifest_sha256"],
        "semantic_registry_sha256": authority["semantic_registry"]["manifest_sha256"],
        "toolchain": authority["toolchain"],
        "runtime_identity": authority["runtime_identity"],
        "evidence_pins": authority["evidence_pins"],
        "executions": executions,
    }


_CHILD_BOOTSTRAP = """
import errno
import os
import resource
import runpy
import socket
import sys

bundle = os.environ["W3_QUALIFIER_BUNDLE"]
worker = os.environ["W3_QUALIFIER_WORKER"]
output_root = os.environ["W3_QUALIFIER_OUTPUT_ROOT"]
denied_path = os.environ["W3_QUALIFIER_DENIED_PATH"]
denied_read_path = os.environ["W3_QUALIFIER_DENIED_READ_PATH"]
limit = int(os.environ["W3_QUALIFIER_FILE_LIMIT"])
resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
os.umask(0o077)

try:
    descriptor = os.open(denied_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except OSError as error:
    if error.errno not in {errno.EPERM, errno.EACCES}:
        raise SystemExit(61)
else:
    os.close(descriptor)
    os.unlink(denied_path)
    raise SystemExit(62)

try:
    descriptor = os.open(denied_read_path, os.O_RDONLY)
except OSError as error:
    if error.errno not in {errno.EPERM, errno.EACCES}:
        raise SystemExit(65)
else:
    os.close(descriptor)
    raise SystemExit(66)

for operation in ("bind", "connect"):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if operation == "bind":
                sock.bind(("127.0.0.1", 0))
            else:
                sock.connect(("127.0.0.1", 0))
        finally:
            sock.close()
    except OSError as error:
        if error.errno not in {errno.EPERM, errno.EACCES}:
            raise SystemExit(63)
    else:
        raise SystemExit(64)

stdlib = [entry for entry in sys.path if entry and "site-packages" not in entry]
sys.path[:] = [bundle, *stdlib]
os.chdir(bundle)
sys.argv = [worker]
runpy.run_path(worker, run_name="__main__")
""".strip()


def _kill_and_reap_process_group(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired as error:
        raise QualificationBlocked("worker process group could not be reaped") from error
    deadline = time.monotonic() + 2
    while True:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        if time.monotonic() >= deadline:
            raise QualificationBlocked("worker descendants remained after process-group kill")
        time.sleep(0.01)


def _run_worker(
    bundle: Path,
    worker_relative: str,
    source_root: Path,
    artifact_root: Path,
    request_bytes: bytes,
    timeout_seconds: float,
) -> tuple[bytes, Path]:
    if len(request_bytes) > MAX_WORKER_INPUT_BYTES:
        raise QualificationBlocked("worker input exceeds its size cap")
    process_root = Path(tempfile.mkdtemp(prefix=".w3-worker-", dir=artifact_root))
    output_root = process_root / "output"
    output_root.mkdir()
    output_root.chmod(0o700)
    stdout_path = process_root / "stdout.json"
    stderr_path = process_root / "stderr.txt"
    denied_path = artifact_root / f".w3-denied-{process_root.name}"
    denied_read_path = source_root / worker_relative
    if denied_path.exists() or denied_path.is_symlink():
        _remove_tree(process_root)
        raise QualificationBlocked("external-write canary path already exists")
    environment = {
        "LANG": "C",
        "LC_ALL": "C",
        "W3_QUALIFIER_BUNDLE": str(bundle),
        "W3_QUALIFIER_WORKER": str(bundle / worker_relative),
        "W3_QUALIFIER_OUTPUT_ROOT": str(output_root),
        "W3_QUALIFIER_DENIED_PATH": str(denied_path),
        "W3_QUALIFIER_DENIED_READ_PATH": str(denied_read_path),
        "W3_QUALIFIER_FILE_LIMIT": str(MAX_WORKER_STDOUT_BYTES),
        "W3_QUALIFIER_PROTOCOL": PROTOCOL,
    }
    launcher = _launcher_identity()
    python_root = Path(launcher["python_executable"]).parent.parent.resolve(strict=True)
    command = [
        launcher["sandbox_exec_path"],
        "-p",
        OUTER_SANDBOX_POLICY_TEMPLATE,
        "-D",
        f"PROCESS_ROOT={process_root.resolve()}",
        "-D",
        f"PYTHON_EXECUTABLE={launcher['python_executable']}",
        "-D",
        f"PYTHON_ROOT={python_root}",
        "-D",
        f"BUNDLE_ROOT={bundle.resolve(strict=True)}",
        "-D",
        f"SOURCE_ROOT={source_root.resolve(strict=True)}",
        "-D",
        f"ARTIFACT_ROOT={artifact_root.resolve(strict=True)}",
        launcher["python_executable"],
        "-I",
        "-S",
        "-B",
        "-c",
        _CHILD_BOOTSTRAP,
    ]
    process: subprocess.Popen[bytes] | None = None
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                cwd=bundle,
                env=environment,
                start_new_session=True,
            )
            try:
                process.communicate(input=request_bytes, timeout=timeout_seconds)
            except subprocess.TimeoutExpired as error:
                _kill_and_reap_process_group(process)
                raise QualificationBlocked("worker exceeded the timeout cap") from error
            returncode = process.returncode
            _kill_and_reap_process_group(process)
    except subprocess.TimeoutExpired as error:
        _remove_tree(process_root)
        raise QualificationBlocked("worker exceeded the timeout cap") from error
    except (OSError, subprocess.SubprocessError) as error:
        if process is not None:
            with contextlib.suppress(QualificationBlocked):
                _kill_and_reap_process_group(process)
        _remove_tree(process_root)
        raise QualificationBlocked("worker could not start in a clean process") from error
    except QualificationBlocked:
        _remove_tree(process_root)
        raise
    if denied_path.exists() or denied_path.is_symlink():
        _remove_tree(process_root)
        raise QualificationBlocked("sandbox allowed the external-write canary")
    try:
        stdout_bytes = _read_regular_file(stdout_path, MAX_WORKER_STDOUT_BYTES, "worker stdout")
        stderr_bytes = _read_regular_file(stderr_path, MAX_WORKER_STDERR_BYTES, "worker stderr")
        if returncode != 0:
            raise QualificationBlocked(f"worker failed with exit status {returncode}")
        if stderr_bytes:
            raise QualificationBlocked("worker emitted unregistered stderr")
    except Exception:
        _remove_tree(process_root)
        raise
    return stdout_bytes, process_root


def _json_diff_paths(left: Any, right: Any, path: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(_json_diff_paths(left[key], right[key], child))
        return paths
    if isinstance(left, list) and isinstance(right, list):
        paths = []
        for index in range(max(len(left), len(right))):
            child = f"{path}[{index}]"
            if index >= len(left) or index >= len(right):
                paths.append(child)
            else:
                paths.extend(_json_diff_paths(left[index], right[index], child))
        return paths
    return [] if left == right else [path]


def _verify_envelope(
    envelope: Any,
    request: dict[str, Any],
    expected_status: str,
    authority: dict[str, Any],
) -> dict[str, Any]:
    envelope = _exact_keys(envelope, {"schema_version", "result", "evidence"}, "envelope")
    _exact_int(envelope["schema_version"], 1, "envelope schema version")
    result = _exact_keys(envelope["result"], RESULT_KEYS, "Oracle result")
    evidence = _exact_keys(envelope["evidence"], EVIDENCE_KEYS, "Oracle evidence")
    _exact_int(result["schema_version"], 1, "Oracle result schema version")
    if result["status"] != expected_status:
        raise QualificationBlocked("Oracle result status does not match its role")
    if evidence["input_sha256"] != canonical_hash(request):
        raise QualificationBlocked("Oracle input hash differs from the reconstructed request")
    if (
        evidence["toolchain_revision"] != authority["toolchain"]["revision"]
        or evidence["toolchain_tree"] != authority["toolchain"]["tree"]
        or result["toolchain"] != authority["toolchain"]
        or result["runtime"] != authority["runtime_identity"]
        or evidence["runtime_identity"] != authority["runtime_identity"]
        or evidence["runtime_sha256"] != canonical_hash(authority["runtime_identity"])
    ):
        raise QualificationBlocked("Oracle toolchain/runtime differs from authority")
    if any(evidence[key] != value for key, value in authority["evidence_pins"].items()):
        raise QualificationBlocked("Oracle evidence differs from its registered pins")
    diagnostics = _validate_diagnostics(
        result["diagnostics"], "Oracle diagnostics", expected_filename=request["filename"]
    )
    ast = result["ast"]
    ir = result["ir"]
    if (
        not isinstance(ast, dict)
        or set(ast) != {"inventory", "signature"}
        or not isinstance(ast["inventory"], dict)
        or not isinstance(ir, dict)
        or set(ir) != {"value", "signature"}
    ):
        raise QualificationBlocked("Oracle result omits typed diagnostic/AST/IR evidence")
    expected_ir_hash = None if ir["value"] is None else canonical_hash(ir["value"])
    if (
        evidence["diagnostics_sha256"] != canonical_hash(diagnostics)
        or ast["signature"] != canonical_hash(ast["inventory"])
        or evidence["ast_sha256"] != ast["signature"]
        or ir["signature"] != expected_ir_hash
        or evidence["ir_sha256"] != expected_ir_hash
        or evidence["metis_status_sha256"] != canonical_hash(evidence["metis_status"])
        or not isinstance(evidence["metis_status"], str)
    ):
        raise QualificationBlocked("Oracle evidence hashes do not match exact result values")
    unsigned = _decode_json(canonical_json_bytes(envelope), "Oracle envelope copy")
    stored = unsigned["evidence"].pop("envelope_sha256")
    if stored != canonical_hash(unsigned):
        raise QualificationBlocked("Oracle envelope hash does not match exact contents")
    endpoint = result["endpoint"]
    if not isinstance(endpoint, dict) or set(endpoint) != {"name", "count"}:
        raise QualificationBlocked("Oracle endpoint evidence is malformed")
    if expected_status == "ok":
        validation_errors = [
            item
            for item in diagnostics["validation"]
            if isinstance(item, dict) and item.get("severity") == 1
        ]
        if (
            result["failure"] is not None
            or diagnostics["parser"]
            or diagnostics["link"]
            or validation_errors
            or not isinstance(ir["value"], dict)
            or not isinstance(endpoint["name"], str)
            or not endpoint["name"]
        ):
            raise QualificationBlocked("Oracle ok result is logically inconsistent")
        _exact_int(endpoint["count"], 1, "Oracle ok endpoint count")
    else:
        _exact_int(endpoint["count"], 0, "Oracle invalid endpoint count")
        failure = _validate_failure(result["failure"], "Oracle failure")
        if (
            endpoint["name"] is not None
            or ir["value"] is not None
            or failure["kind"] not in {"parse", "link", "validation"}
        ):
            raise QualificationBlocked("Oracle invalid result is logically inconsistent")
    return result


def _verify_semantics(
    candidates: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    results: dict[tuple[str, str], dict[str, Any]],
) -> None:
    for candidate_id, candidate in candidates.items():
        family = candidate["family"]
        truth = specs[candidate_id]["semantic_spec"]["truth"]
        endpoint = truth["expected_endpoint"]
        if family == "F-1":
            result = results[(candidate_id, "author")]
            matched = (
                candidate["request"] == truth["request_exact"]
                and all(
                    fragment in candidate["target_source"]
                    for fragment in truth["required_source_fragments"]
                )
                and result["status"] == "ok"
                and result["endpoint"]["name"] == endpoint
                and result["ir"]["value"] == truth["expected_ir"]
            )
        elif family == "F-2":
            before = candidate["before_source"]
            after = candidate["after_source"]
            before_result = results[(candidate_id, "before")]
            after_result = results[(candidate_id, "after")]
            exact_edit = before.count(truth["old_text"]) == truth[
                "occurrences"
            ] and after == before.replace(
                truth["old_text"], truth["new_text"], truth["occurrences"]
            )
            expected_delta = {
                "replace": {"old_text": truth["old_text"], "new_text": truth["new_text"]}
            }
            before_ir = before_result["ir"]["value"]
            after_ir = after_result["ir"]["value"]
            matched = (
                exact_edit
                and candidate["expected_delta"] == expected_delta
                and before_result["status"] == after_result["status"] == "ok"
                and before_result["endpoint"]["name"] == endpoint
                and after_result["endpoint"]["name"] == endpoint
                and before_ir == truth["expected_before_ir"]
                and after_ir == truth["expected_after_ir"]
                and _json_diff_paths(before_ir, after_ir) == truth["expected_changed_paths"]
            )
        else:
            mutated = results[(candidate_id, "mutated")]
            fixed = results[(candidate_id, "fixed")]
            expected_diagnostic = {
                "failure_kind": truth["expected_failure_kind"],
                "diagnostic_present": truth["expected_diagnostic_present"],
            }
            expected_mutation = {"operation": "remove", "fragment": truth["repair_fragment"]}
            exact_mutation = candidate["fixed_source"].count(
                truth["repair_fragment"]
            ) == 1 and candidate["mutated_source"] == candidate["fixed_source"].replace(
                truth["repair_fragment"], "", 1
            )
            matched = (
                mutated["status"] == "invalid"
                and mutated["failure"] == truth["expected_failure"]
                and mutated["diagnostics"] == truth["expected_diagnostics"]
                and fixed["status"] == "ok"
                and fixed["endpoint"]["name"] == endpoint
                and fixed["ir"]["value"] == truth["expected_fixed_ir"]
                and candidate["expected_diagnostic"] == expected_diagnostic
                and candidate["mutation_spec"] == expected_mutation
                and exact_mutation
            )
        if not matched:
            raise QualificationBlocked(f"candidate {candidate_id} fails exact registered truth")


def _verify_worker_output(
    stdout_bytes: bytes,
    output_root: Path,
    request: dict[str, Any],
    request_bytes: bytes,
    authority: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    output = _decode_json(stdout_bytes, "worker stdout", require_canonical=True)
    output_keys = {
        "schema_version",
        "protocol",
        "authority_manifest_sha256",
        "bundle_sha256",
        "input_sha256",
        "status",
        "matched",
        "executions",
        "counts",
        "roles",
        "run_sha256",
    }
    output = _exact_keys(output, output_keys, "worker output")
    _exact_int(output["schema_version"], 1, "worker output schema version")
    if (
        output["protocol"] != PROTOCOL
        or output["status"] != "completed"
        or output["authority_manifest_sha256"] != request["authority_manifest_sha256"]
        or output["bundle_sha256"] != request["bundle_sha256"]
        or output["input_sha256"] != _bytes_hash(request_bytes)
    ):
        raise QualificationBlocked("worker output is not bound to its canonical input")
    if type(output["matched"]) is not bool:
        raise QualificationBlocked("worker matched field must be a strict boolean")
    run_body = {key: item for key, item in output.items() if key != "run_sha256"}
    if output["run_sha256"] != canonical_hash(run_body):
        raise QualificationBlocked("worker run hash does not match exact output")
    executions = output["executions"]
    if not isinstance(executions, list) or len(executions) != 5:
        raise QualificationBlocked("worker execution roster is not exact")
    expected_by_key = {(item["candidate_id"], item["role"]): item for item in request["executions"]}
    seen: set[tuple[str, str]] = set()
    results: dict[tuple[str, str], dict[str, Any]] = {}
    verified: list[dict[str, Any]] = []
    artifact_names: set[str] = set()
    for index, item in enumerate(executions):
        keys = {
            "candidate_id",
            "family",
            "role",
            "request",
            "request_sha256",
            "envelope",
            "envelope_sha256",
            "result_sha256",
            "artifact_path",
            "artifact_sha256",
        }
        item = _exact_keys(item, keys, f"worker execution {index}")
        if (
            not isinstance(item["candidate_id"], str)
            or CANDIDATE_ID_PATTERN.fullmatch(item["candidate_id"]) is None
            or item["family"] not in ROLE_CONTRACT
            or not isinstance(item["role"], str)
        ):
            raise QualificationBlocked("worker execution identity is invalid")
        key = (item["candidate_id"], item["role"])
        if key in seen or key not in expected_by_key:
            raise QualificationBlocked("worker returned a duplicate or mixed-role execution")
        expected = expected_by_key[key]
        if item["family"] != expected["family"] or item["request"] != expected["request"]:
            raise QualificationBlocked("worker execution differs from reconstructed role/request")
        if item["request_sha256"] != canonical_hash(expected["request"]):
            raise QualificationBlocked("worker request hash is invalid")
        result = _verify_envelope(
            item["envelope"], expected["request"], expected["expected_status"], authority
        )
        if item["envelope_sha256"] != canonical_hash(item["envelope"]) or item[
            "result_sha256"
        ] != canonical_hash(result):
            raise QualificationBlocked("worker envelope/result hash is invalid")
        relative = _safe_relative_path(item["artifact_path"], "worker artifact path")
        if (
            relative.as_posix() != item["artifact_path"]
            or ARTIFACT_PATH_PATTERN.fullmatch(item["artifact_path"]) is None
            or relative.parts[0] != "artifacts"
            or relative.as_posix() in artifact_names
        ):
            raise QualificationBlocked("worker artifact path is outside the registered namespace")
        artifact_names.add(relative.as_posix())
        artifact = _source_file(output_root, relative, "worker artifact")
        raw = _read_regular_file(artifact, MAX_ARTIFACT_BYTES, "worker artifact")
        if raw != canonical_json_bytes(item["envelope"]):
            raise QualificationBlocked("worker artifact bytes differ from the envelope")
        if item["artifact_sha256"] != _bytes_hash(raw):
            raise QualificationBlocked("worker artifact hash is invalid")
        seen.add(key)
        results[key] = result
        verified.append(
            {
                "candidate_id": key[0],
                "family": item["family"],
                "role": key[1],
                "request_sha256": item["request_sha256"],
                "envelope_sha256": item["envelope_sha256"],
                "result_sha256": item["result_sha256"],
                "artifact_path": relative.as_posix(),
                "artifact_sha256": item["artifact_sha256"],
            }
        )
    if seen != set(expected_by_key):
        raise QualificationBlocked("worker execution roster has gaps")
    role_counts = dict(sorted(Counter(role for _, role in seen).items()))
    counts = {
        "candidates": len({candidate_id for candidate_id, _ in seen}),
        "executions": len(seen),
        "distinct": len(seen),
        "gaps": len(set(expected_by_key) - seen),
    }
    _exact_count_map(output["roles"], EXPECTED_ROLE_COUNTS, "worker role counts")
    _exact_count_map(
        output["counts"],
        {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0},
        "worker counts",
    )
    if output["roles"] != role_counts or output["counts"] != counts:
        raise QualificationBlocked("worker role/count claims differ from recomputed values")
    if counts != {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0}:
        raise QualificationBlocked("recomputed qualification denominator is not exact")
    _verify_semantics(candidates, specs, results)
    actual_files = {
        item.relative_to(output_root).as_posix()
        for item in output_root.rglob("*")
        if item.is_file()
    }
    if actual_files != artifact_names or any(item.is_symlink() for item in output_root.rglob("*")):
        raise QualificationBlocked("worker output root contains unregistered files")
    return {"counts": counts, "roles": role_counts}, sorted(
        verified, key=lambda item: (item["candidate_id"], item["role"])
    )


def _expected_tree_directories(files: set[str]) -> set[str]:
    directories = {
        parent.as_posix()
        for name in files
        for parent in PurePosixPath(name).parents
        if parent.as_posix() != "."
    }
    return directories


def _snapshot_qualification_tree(
    root: Path,
    expected_files: set[str],
    *,
    immutable: bool,
) -> dict[str, bytes]:
    if root.is_symlink() or not root.is_dir():
        raise QualificationBlocked("qualification tree root is not a regular directory")
    root_mode = 0o555 if immutable else 0o700
    directory_mode = 0o555 if immutable else 0o700
    file_mode = 0o444 if immutable else 0o600
    if stat.S_IMODE(root.lstat().st_mode) != root_mode:
        raise QualificationBlocked("qualification tree root mode changed")
    items = list(root.rglob("*"))
    if any(item.is_symlink() for item in items):
        raise QualificationBlocked("qualification tree contains a symlink")
    actual_files = {item.relative_to(root).as_posix() for item in items if item.is_file()}
    actual_directories = {item.relative_to(root).as_posix() for item in items if item.is_dir()}
    if (
        actual_files != expected_files
        or actual_directories != _expected_tree_directories(expected_files)
        or any(not item.is_file() and not item.is_dir() for item in items)
    ):
        raise QualificationBlocked("qualification tree roster changed")
    if any(stat.S_IMODE(item.lstat().st_mode) != directory_mode for item in items if item.is_dir()):
        raise QualificationBlocked("qualification directory mode changed")
    snapshot: dict[str, bytes] = {}
    total = 0
    for name in sorted(actual_files):
        path = root / name
        if stat.S_IMODE(path.lstat().st_mode) != file_mode:
            raise QualificationBlocked("qualification file mode changed")
        limit = MAX_REPORT_BYTES if name == "qualification.json" else MAX_ARTIFACT_BYTES
        raw = _read_regular_file(path, limit, f"qualification file {name}")
        total += len(raw)
        if total > MAX_PUBLISHED_BYTES:
            raise QualificationBlocked("qualification tree exceeds its aggregate size cap")
        snapshot[name] = raw
    return snapshot


def _validate_report(report: Any, launcher: dict[str, Any]) -> None:
    keys = {
        "schema_version",
        "qualification_id",
        "status",
        "claim",
        "authority_manifest_sha256",
        "bundle_sha256",
        "semantic_registry_sha256",
        "candidate_manifest_sha256",
        "worker_input_sha256",
        "worker_output_sha256",
        "launcher",
        "counts",
        "roles",
        "executions",
        "stops",
        "manifest_sha256",
    }
    report = _exact_keys(report, keys, "qualification report")
    _exact_int(report["schema_version"], 1, "qualification report schema version")
    if (
        report["qualification_id"] != QUALIFICATION_ID
        or report["status"] != "qualified"
        or report["claim"] != CLAIM
        or report["launcher"] != launcher
        or report["stops"] != QUALIFICATION_STOPS
    ):
        raise QualificationBlocked("qualification report contract is invalid")
    for name in (
        "authority_manifest_sha256",
        "bundle_sha256",
        "semantic_registry_sha256",
        "candidate_manifest_sha256",
        "worker_input_sha256",
        "worker_output_sha256",
        "manifest_sha256",
    ):
        if not _valid_hash(report[name]):
            raise QualificationBlocked("qualification report contains an invalid digest")
    _exact_keys(report["launcher"], LAUNCHER_IDENTITY_KEYS, "report launcher identity")
    _exact_count_map(
        report["counts"],
        {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0},
        "report counts",
    )
    _exact_count_map(report["roles"], EXPECTED_ROLE_COUNTS, "report roles")
    executions = report["executions"]
    if not isinstance(executions, list) or len(executions) != 5:
        raise QualificationBlocked("qualification report execution roster is invalid")
    seen: set[tuple[str, str]] = set()
    artifact_paths: set[str] = set()
    for index, execution in enumerate(executions):
        execution = _exact_keys(
            execution,
            {
                "candidate_id",
                "family",
                "role",
                "request_sha256",
                "envelope_sha256",
                "result_sha256",
                "artifact_path",
                "artifact_sha256",
            },
            f"qualification report execution {index}",
        )
        candidate_id = execution["candidate_id"]
        family = execution["family"]
        role = execution["role"]
        if (
            not isinstance(candidate_id, str)
            or CANDIDATE_ID_PATTERN.fullmatch(candidate_id) is None
            or family not in ROLE_CONTRACT
            or role not in {item[0] for item in ROLE_CONTRACT[family]}
            or (candidate_id, role) in seen
        ):
            raise QualificationBlocked("qualification report execution identity is invalid")
        artifact_path = execution["artifact_path"]
        if (
            not isinstance(artifact_path, str)
            or ARTIFACT_PATH_PATTERN.fullmatch(artifact_path) is None
            or _safe_relative_path(artifact_path, "report artifact path").as_posix()
            != artifact_path
            or artifact_path in artifact_paths
        ):
            raise QualificationBlocked("qualification report artifact path is invalid")
        if any(
            not _valid_hash(execution[name])
            for name in (
                "request_sha256",
                "envelope_sha256",
                "result_sha256",
                "artifact_sha256",
            )
        ):
            raise QualificationBlocked("qualification report execution digest is invalid")
        seen.add((candidate_id, role))
        artifact_paths.add(artifact_path)
    if len({candidate_id for candidate_id, _ in seen}) != 3:
        raise QualificationBlocked("qualification report candidate denominator is invalid")
    body = {key: item for key, item in report.items() if key != "manifest_sha256"}
    if report["manifest_sha256"] != canonical_hash(body):
        raise QualificationBlocked("qualification report digest is invalid")
    if len(canonical_json_bytes(report)) > MAX_REPORT_BYTES:
        raise QualificationBlocked("qualification report exceeds its size cap")


def _publish_qualification(artifact_root: Path, process_root: Path, report: dict[str, Any]) -> None:
    target = artifact_root / "qualifications" / report["manifest_sha256"][len(HASH_PREFIX) :]
    qualifications_root = target.parent
    if qualifications_root.is_symlink():
        raise QualificationBlocked("qualification namespace may not be a symlink")
    qualifications_root.mkdir(parents=True, exist_ok=True)
    if qualifications_root.is_symlink() or not qualifications_root.is_dir():
        raise QualificationBlocked("qualification namespace is invalid")
    source = process_root / "output"
    report_path = source / "qualification.json"
    report_path.write_bytes(canonical_json_bytes(report))
    report_path.chmod(0o600)
    expected_files = {item["artifact_path"] for item in report["executions"]} | {
        "qualification.json"
    }
    mutable_snapshot = _snapshot_qualification_tree(source, expected_files, immutable=False)
    if target.is_symlink():
        raise QualificationBlocked("qualification target may not be a symlink")
    if target.exists():
        existing = _snapshot_qualification_tree(target, expected_files, immutable=True)
        if existing != mutable_snapshot:
            raise QualificationBlocked("existing qualification artifact differs from replay")
        return
    try:
        source.rename(target)
    except FileExistsError as error:
        existing = _snapshot_qualification_tree(target, expected_files, immutable=True)
        if existing != mutable_snapshot:
            raise QualificationBlocked(
                "raced qualification artifact differs from replay"
            ) from error
        return
    try:
        for item in sorted(target.rglob("*"), key=lambda value: len(value.parts), reverse=True):
            item.chmod(0o555 if item.is_dir() else 0o444)
        target.chmod(0o555)
        published = _snapshot_qualification_tree(target, expected_files, immutable=True)
        if published != mutable_snapshot:
            raise QualificationBlocked("published qualification artifact changed")
    except Exception:
        _remove_tree(target)
        raise


def _qualify_impl(
    *,
    authority_path: str | os.PathLike[str],
    authority_sha256: str,
    source_root: str | os.PathLike[str],
    artifact_root: str | os.PathLike[str],
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Run the bounded verifier once and return its canonical report object."""

    launcher_before = _launcher_identity()
    if type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise QualificationBlocked("timeout must be positive and within the registered cap")
    try:
        source = Path(source_root).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise QualificationBlocked("source root is unavailable") from error
    if not source.is_dir():
        raise QualificationBlocked("source root is not a directory")
    artifact = Path(artifact_root).absolute()
    try:
        artifact_resolved = artifact.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise QualificationBlocked("artifact root is invalid") from error
    if (
        artifact_resolved == source
        or source in artifact_resolved.parents
        or artifact_resolved in source.parents
    ):
        raise QualificationBlocked("artifact root must be outside the source/Git root")
    try:
        authority_file = Path(authority_path).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise QualificationBlocked("authority manifest is unavailable") from error
    if (
        authority_file in (source, artifact_resolved)
        or source in authority_file.parents
        or artifact_resolved in authority_file.parents
    ):
        raise QualificationBlocked("authority manifest must be external to source and artifacts")

    # All authority and source-byte checks occur before the artifact root is
    # created and, critically, before any child process exists.
    authority = _load_authority(authority_file, authority_sha256)
    material, contents = _read_bundle_sources(authority, source)
    candidates, specs, executions = _load_gate_inputs(authority, contents)

    artifact_resolved.mkdir(parents=True, exist_ok=True)
    bundle, bundle_sha256, bundle_body = _materialize_bundle(
        artifact_resolved, authority_sha256, material, contents
    )
    request = _worker_input(authority, authority_sha256, bundle_sha256, executions)
    request_bytes = canonical_json_bytes(request)
    stdout_bytes, process_root = _run_worker(
        bundle,
        authority["worker"]["path"],
        source,
        artifact_resolved,
        request_bytes,
        float(timeout_seconds),
    )
    try:
        denominators, verified = _verify_worker_output(
            stdout_bytes,
            process_root / "output",
            request,
            request_bytes,
            authority,
            candidates,
            specs,
        )
        _verify_materialized_bundle(bundle, bundle_body, contents)
        launcher_after = _launcher_identity()
        if launcher_after != launcher_before or launcher_after != authority["launcher"]:
            raise QualificationBlocked("launcher identity changed during qualification")
        report_body = {
            "schema_version": SCHEMA_VERSION,
            "qualification_id": QUALIFICATION_ID,
            "status": "qualified",
            "claim": CLAIM,
            "authority_manifest_sha256": authority_sha256,
            "bundle_sha256": bundle_sha256,
            "semantic_registry_sha256": authority["semantic_registry"]["manifest_sha256"],
            "candidate_manifest_sha256": authority["candidate_manifest"]["manifest_sha256"],
            "worker_input_sha256": _bytes_hash(request_bytes),
            "worker_output_sha256": _bytes_hash(stdout_bytes),
            "launcher": launcher_before,
            "counts": denominators["counts"],
            "roles": denominators["roles"],
            "executions": verified,
            "stops": list(QUALIFICATION_STOPS),
        }
        report = {**report_body, "manifest_sha256": canonical_hash(report_body)}
        _validate_report(report, launcher_before)
        _publish_qualification(artifact_resolved, process_root, report)
        return report
    finally:
        _remove_tree(process_root)


def qualify(
    *,
    authority_path: str | os.PathLike[str],
    authority_sha256: str,
    source_root: str | os.PathLike[str],
    artifact_root: str | os.PathLike[str],
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Fail closed, including for malformed nested input that raises unexpectedly."""

    try:
        _require_launcher_flags()
        return _qualify_impl(
            authority_path=authority_path,
            authority_sha256=authority_sha256,
            source_root=source_root,
            artifact_root=artifact_root,
            timeout_seconds=timeout_seconds,
        )
    except QualificationBlocked:
        raise
    except Exception as error:
        raise QualificationBlocked(
            "malformed input caused an internal verifier rejection"
        ) from error


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "qualification_id": QUALIFICATION_ID,
        "status": "blocked",
        "claim": "no_qualification_claim",
        "reason": reason,
    }


class _CanonicalArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise QualificationBlocked(f"invalid command line: {message}")


def main(argv: list[str] | None = None) -> int:
    parser = _CanonicalArgumentParser(description=__doc__)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--authority-sha256", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    try:
        _require_launcher_flags()
        arguments = parser.parse_args(argv)
        report = qualify(
            authority_path=arguments.authority,
            authority_sha256=arguments.authority_sha256,
            source_root=arguments.source_root,
            artifact_root=arguments.artifact_root,
            timeout_seconds=arguments.timeout_seconds,
        )
    except QualificationBlocked as error:
        sys.stdout.buffer.write(canonical_json_bytes(_blocked(str(error))) + b"\n")
        return 2
    sys.stdout.buffer.write(canonical_json_bytes(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
