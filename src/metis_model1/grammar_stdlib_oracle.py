"""Bounded grammar-and-stdlib oracle over the catalog-maintenance pin.

This lane deliberately consumes only the pinned ``tooling`` Git archive.  It
never opens a tenant/example path from the Metis checkout: caller-supplied
source is installed in-memory by the existing Model 1 runner.  The temporary
snapshot is run under the catalog-maintenance sandbox, which denies network and
writes, and is discarded after every invocation.

It is an evaluator helper, not a training or promotion authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from metis_model1 import catalog_maintenance_pin as catalog_pin
from metis_model1 import catalog_retrieval_refresh as refresh
from metis_model1 import oracles

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OVERLAY_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-pin-v1.json"
RUNNER_PATH = PROJECT_ROOT / "runtime/metis_oracle/runner.ts"
LOADER_PATH = PROJECT_ROOT / "runtime/metis_oracle/native_ts_loader.mjs"

SCHEMA_VERSION = 1
LANGUAGE_VERSION = "0.43"
MAX_SOURCE_BYTES = 512 * 1024
MAX_WORKSPACE_SOURCES = 64
MAX_STDOUT_BYTES = 8 * 1024 * 1024
MAX_STDERR_BYTES = 128 * 1024
MAX_SESSION_FILESYSTEM_ENTRIES = 64 * 1024
_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\.metis$")
_SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_RAW_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_OVERLAY_PATHS = {
    "grammar": "tooling/src/language/metis.langium",
    "generated_grammar": "tooling/src/language/generated/grammar.ts",
    "stdlib": "tooling/src/language/stdlib-schema.ts",
    "version": "tooling/src/language/version.ts",
    "guard_eval": "tooling/src/compiler/guard-eval.ts",
    "corpus_validation_test": "tooling/test/corpus-validation.ts",
    "time_test": "tooling/test/time-rule.ts",
    "compiler_regression_test": "tooling/test/compiler-regression.ts",
}


class GrammarStdlibOracleError(ValueError):
    """Raised when grammar/stdlib evidence cannot be established safely."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise GrammarStdlibOracleError("value is not canonical JSON") from error


def _sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _bytes_sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _safe_filename(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _FILENAME_RE.fullmatch(value):
        raise GrammarStdlibOracleError(f"{label} must be a bounded relative .metis path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise GrammarStdlibOracleError(f"{label} must be a bounded relative .metis path")
    return value


def _safe_source(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise GrammarStdlibOracleError(f"{label} must be a bounded non-empty UTF-8 source")
    return value


def _workspace(value: Mapping[str, str] | None, filename: str) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, Mapping) or len(value) > MAX_WORKSPACE_SOURCES:
        raise GrammarStdlibOracleError("workspace_sources is not a bounded mapping")
    rows: list[dict[str, str]] = []
    for name, source in value.items():
        safe_name = _safe_filename(name, "workspace filename")
        if safe_name == filename:
            raise GrammarStdlibOracleError("workspace filename duplicates the candidate")
        rows.append({"filename": safe_name, "source": _safe_source(source, "workspace source")})
    rows.sort(key=lambda item: item["filename"])
    if len({item["filename"] for item in rows}) != len(rows):
        raise GrammarStdlibOracleError("workspace filenames are not distinct")
    return rows


def _stable_regular_bytes(path: Path, label: str, limit: int = 2 * 1024 * 1024) -> bytes:
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        opened = os.fstat(descriptor)
        if not path.is_file() or path.is_symlink() or opened.st_size > limit:
            raise GrammarStdlibOracleError(f"{label} is not a bounded regular file")
        raw = os.read(descriptor, opened.st_size + 1)
        after = os.fstat(descriptor)
        named_after = path.lstat()
    except OSError as error:
        raise GrammarStdlibOracleError(f"{label} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity = lambda item: (  # noqa: E731 - compact immutable stat identity
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_nlink,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if (
        len(raw) != opened.st_size
        or identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(named_after)
    ):
        raise GrammarStdlibOracleError(f"{label} changed while it was read")
    return raw


def _overlay(metis_root: Path, base: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate an optional overlay solely against fixed tooling Git blobs."""

    if not OVERLAY_PATH.exists():
        return None
    raw = _stable_regular_bytes(OVERLAY_PATH, "grammar/stdlib pin overlay")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GrammarStdlibOracleError("grammar/stdlib pin overlay is not JSON") from error
    expected_fields = {
        "schema_version",
        "pin_id",
        "repository",
        "revision",
        "tree",
        "language_version",
        "grammar",
        "stdlib",
        "version_evidence",
        "comparison",
        "policy",
        "nonclaims",
        "evidence",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise GrammarStdlibOracleError("grammar/stdlib pin overlay has an invalid field roster")
    if (
        value["schema_version"] != 1
        or value["pin_id"] != "grammar-stdlib/2026-08-25-v1"
        or value["repository"] != "ares-matioska/metis"
        or value["revision"] != base["revision"]
        or value["tree"] != base["tree"]
        or value["language_version"] != LANGUAGE_VERSION
    ):
        raise GrammarStdlibOracleError(
            "grammar/stdlib pin overlay identity differs from catalog pin"
        )
    if (
        not isinstance(value["policy"], dict)
        or set(value["policy"])
        != {
            "git_objects_only",
            "worktree_payloads_excluded",
            "untracked_worktree_excluded",
            "credentials_and_env_excluded",
            "no_model_execution",
            "no_training_authority",
            "no_external_writes",
        }
        or any(item is not True for item in value["policy"].values())
        or value["nonclaims"]
        != [
            "no_tenant_payload",
            "no_model_output",
            "no_training_authority",
            "no_accuracy_claim",
            "no_runtime_parity_claim",
            "nonpromotable",
        ]
    ):
        raise GrammarStdlibOracleError("grammar/stdlib pin overlay policy drift")
    comparison = value["comparison"]
    if (
        not isinstance(comparison, dict)
        or set(comparison) != {"revision", "tree", "same_evidence_blobs"}
        or comparison.get("same_evidence_blobs") is not True
        or not isinstance(comparison.get("revision"), str)
        or _OID_RE.fullmatch(comparison["revision"]) is None
        or not isinstance(comparison.get("tree"), str)
        or _OID_RE.fullmatch(comparison["tree"]) is None
    ):
        raise GrammarStdlibOracleError("grammar/stdlib pin overlay comparison drift")
    comparison_tree = str(
        catalog_pin._run_git(metis_root, "rev-parse", f"{comparison['revision']}^{{tree}}")
    )
    if comparison_tree != comparison["tree"]:
        raise GrammarStdlibOracleError("grammar/stdlib overlay comparison tree drift")
    evidence = value["evidence"]
    if not isinstance(evidence, list) or len(evidence) != len(_OVERLAY_PATHS):
        raise GrammarStdlibOracleError("grammar/stdlib pin overlay evidence roster is incomplete")
    seen: set[str] = set()
    normalized: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"id", "path", "blob_oid", "sha256"}:
            raise GrammarStdlibOracleError("grammar/stdlib pin overlay evidence entry is invalid")
        evidence_id = item["id"]
        if (
            not isinstance(evidence_id, str)
            or evidence_id in seen
            or evidence_id not in _OVERLAY_PATHS
        ):
            raise GrammarStdlibOracleError("grammar/stdlib pin overlay evidence IDs drift")
        if (
            item["path"] != _OVERLAY_PATHS[evidence_id]
            or not isinstance(item["blob_oid"], str)
            or _OID_RE.fullmatch(item["blob_oid"]) is None
            or not isinstance(item["sha256"], str)
            or _RAW_SHA_RE.fullmatch(item["sha256"]) is None
        ):
            raise GrammarStdlibOracleError(
                "grammar/stdlib pin overlay evidence identity is invalid"
            )
        row = str(
            catalog_pin._run_git(metis_root, "ls-tree", base["revision"], "--", item["path"])
        ).split()
        if len(row) != 4 or row[:2] != ["100644", "blob"] or row[2] != item["blob_oid"]:
            raise GrammarStdlibOracleError(
                f"grammar/stdlib overlay Git identity drift: {item['path']}"
            )
        comparison_row = str(
            catalog_pin._run_git(metis_root, "ls-tree", comparison["revision"], "--", item["path"])
        ).split()
        if comparison_row != row:
            raise GrammarStdlibOracleError(
                f"grammar/stdlib overlay comparison blob drift: {item['path']}"
            )
        blob = catalog_pin._run_git(metis_root, "cat-file", "blob", item["blob_oid"], text=False)
        assert isinstance(blob, bytes)
        if _bytes_sha(blob).removeprefix("sha256:") != item["sha256"]:
            raise GrammarStdlibOracleError(f"grammar/stdlib overlay content drift: {item['path']}")
        declared = {
            "grammar": value["grammar"],
            "stdlib": value["stdlib"],
            "version": value["version_evidence"],
        }.get(evidence_id)
        if declared is not None and (
            not isinstance(declared, dict)
            or declared.get("path") != item["path"]
            or declared.get("blob_oid") != item["blob_oid"]
            or declared.get("sha256") != item["sha256"]
        ):
            raise GrammarStdlibOracleError(
                f"grammar/stdlib overlay declaration drift: {evidence_id}"
            )
        seen.add(evidence_id)
        normalized.append(
            {
                "id": evidence_id,
                "path": item["path"],
                "sha256": "sha256:" + item["sha256"],
            }
        )
    if seen != set(_OVERLAY_PATHS):
        raise GrammarStdlibOracleError("grammar/stdlib pin overlay evidence roster is incomplete")
    return {
        "pin_id": value["pin_id"],
        "file_sha256": _bytes_sha(raw),
        "evidence": sorted(normalized, key=lambda item: item["id"]),
    }


def validate_grammar_stdlib_pin(*, metis_root: Path) -> dict[str, Any]:
    """Pure validation of the fixed catalog pin and an optional stdlib overlay.

    The helper reads only the pin, the optional overlay, Git objects under the
    pinned revision, and pinned tooling runtime metadata.  It performs no
    archive construction and no compiler invocation.
    """

    try:
        errors = catalog_pin.validate_catalog_maintenance_pin_contract()
        if errors:
            raise GrammarStdlibOracleError(
                "catalog maintenance pin is invalid: " + "; ".join(errors)
            )
        base = catalog_pin.load_catalog_maintenance_pin()
        root = Path(metis_root).resolve(strict=True)
        if not root.is_dir():
            raise GrammarStdlibOracleError("metis_root must be a directory")
        revision = str(catalog_pin._run_git(root, "rev-parse", base["revision"]))
        tree = str(catalog_pin._run_git(root, "rev-parse", f"{base['revision']}^{{tree}}"))
        if revision != base["revision"] or tree != base["tree"]:
            raise GrammarStdlibOracleError(
                "Metis repository does not contain the exact catalog pin"
            )
        tracked = str(
            catalog_pin._run_git(root, "status", "--porcelain=v1", "--untracked-files=no")
        )
        if tracked:
            raise GrammarStdlibOracleError(
                "Metis tracked working tree differs from the pinned commit"
            )
        overlay = _overlay(root, base)
        return {
            "catalog_pin_id": base["pin_id"],
            "catalog_pin_sha256": catalog_pin.manifest_sha256(base),
            "revision": base["revision"],
            "tree": base["tree"],
            "language_version": LANGUAGE_VERSION,
            "overlay": overlay,
        }
    except catalog_pin.CatalogMaintenancePinError as error:
        raise GrammarStdlibOracleError(str(error)) from error
    except OSError as error:
        raise GrammarStdlibOracleError("metis_root is unavailable") from error


def _runner_bytes(path: Path, expected_sha256: str, label: str) -> bytes:
    raw = _stable_regular_bytes(path, label)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise GrammarStdlibOracleError(f"{label} differs from the pinned Model 1 runtime")
    return raw


def _install_runner(snapshot: refresh._Snapshot, identity: Mapping[str, Any]) -> tuple[Path, Path]:
    runner_raw = _runner_bytes(RUNNER_PATH, oracles.PINNED_RUNNER_SHA256, "oracle runner")
    loader_raw = _runner_bytes(LOADER_PATH, oracles.PINNED_LOADER_SHA256, "oracle loader")
    runtime_dir = snapshot.root / ".metis-oracle"
    runtime_dir.mkdir(mode=0o700, exist_ok=False)
    runner = runtime_dir / "runner.ts"
    loader = runtime_dir / "native_ts_loader.mjs"
    runner.write_bytes(runner_raw)
    loader.write_bytes(loader_raw)
    runner.chmod(0o400)
    loader.chmod(0o400)
    node_sha = "sha256:" + hashlib.sha256(snapshot.node.read_bytes()).hexdigest()
    runtime_identity = {
        "revision": identity["revision"],
        "tree": identity["tree"],
        "package_sha256": identity["runtime"]["package_sha256"].removeprefix("sha256:"),
        "lock_sha256": identity["runtime"]["lock_sha256"].removeprefix("sha256:"),
        "node_modules_sha256": identity["runtime"]["node_modules_sha256"].removeprefix("sha256:"),
        "runner_sha256": oracles.PINNED_RUNNER_SHA256,
        "loader_sha256": oracles.PINNED_LOADER_SHA256,
        "loader_flags": list(oracles.LOADER_FLAGS),
        "node_binary_sha256": node_sha.removeprefix("sha256:"),
        "sandbox_exec_path": oracles.SANDBOX_EXEC_IDENTITY,
        "oracle_policy_version": oracles.SANDBOX_POLICY_VERSION,
        "oracle_policy_sha256": oracles.SANDBOX_POLICY_SHA256,
        "execution_policy_sha256": oracles.SANDBOX_POLICY_SHA256,
    }
    (snapshot.root / ".metis-oracle-identity.json").write_bytes(_canonical(runtime_identity))
    return runner, loader


def _validated_result(
    value: Any,
    *,
    identity: Mapping[str, Any],
    mode: str,
    requested_endpoint: str | None = None,
) -> dict[str, Any]:
    expected_fields = {
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
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise GrammarStdlibOracleError("oracle runner result has an invalid field roster")
    if value["schema_version"] != 1 or value["status"] not in {"ok", "invalid"}:
        raise GrammarStdlibOracleError("oracle runner result has an invalid status")
    if value["toolchain"] != {
        "revision": identity["revision"],
        "tree": identity["tree"],
        "language_version": LANGUAGE_VERSION,
    }:
        raise GrammarStdlibOracleError("oracle runner result toolchain identity drift")
    if (
        not isinstance(value["diagnostics"], dict)
        or not isinstance(value["ast"], dict)
        or not isinstance(value["ir"], dict)
        or not isinstance(value["endpoint"], dict)
    ):
        raise GrammarStdlibOracleError("oracle runner omitted diagnostics, AST, or IR evidence")
    if set(value["diagnostics"]) != {"parser", "link", "validation", "all"} or any(
        not isinstance(item, list) for item in value["diagnostics"].values()
    ):
        raise GrammarStdlibOracleError("oracle runner diagnostics roster drift")
    if set(value["ast"]) != {"inventory", "signature"} or set(value["ir"]) != {
        "value",
        "signature",
    }:
        raise GrammarStdlibOracleError("oracle runner AST or IR roster drift")
    if set(value["endpoint"]) != {"name", "count"} or not isinstance(
        value["endpoint"].get("count"), int
    ):
        raise GrammarStdlibOracleError("oracle runner endpoint evidence drift")
    if value["ast"].get("signature") != _sha(value["ast"].get("inventory")):
        raise GrammarStdlibOracleError("oracle runner AST signature is not canonical")
    expected_ir = None if value["ir"].get("value") is None else _sha(value["ir"]["value"])
    if value["ir"].get("signature") != expected_ir:
        raise GrammarStdlibOracleError("oracle runner IR signature is not canonical")
    runtime = value["runtime"]
    if (
        not isinstance(runtime, dict)
        or runtime.get("snapshot_revision") != identity["revision"]
        or runtime.get("snapshot_tree") != identity["tree"]
    ):
        raise GrammarStdlibOracleError("oracle runner runtime snapshot identity drift")
    expected_runtime = {
        "node": identity["runtime"]["node_version"],
        "node_path": oracles.NODE_RUNTIME_IDENTITY,
        "loader_sha256": "sha256:" + oracles.PINNED_LOADER_SHA256,
        "loader_flags": list(oracles.LOADER_FLAGS),
        "runner_path": f"snapshot://{identity['revision']}/{identity['tree']}/.metis-oracle/runner.ts",
        "loader_path": f"snapshot://{identity['revision']}/{identity['tree']}/.metis-oracle/native_ts_loader.mjs",
        "snapshot_revision": identity["revision"],
        "snapshot_tree": identity["tree"],
        "tooling_package_sha256": identity["runtime"]["package_sha256"],
        "tooling_lock_sha256": identity["runtime"]["lock_sha256"],
        "node_modules_sha256": identity["runtime"]["node_modules_sha256"],
        "node_binary_sha256": identity["runtime"]["node_sha256"],
        "sandbox_exec_path": oracles.SANDBOX_EXEC_IDENTITY,
        "oracle_policy_version": oracles.SANDBOX_POLICY_VERSION,
        "oracle_policy_sha256": "sha256:" + oracles.SANDBOX_POLICY_SHA256,
        "execution_policy_sha256": "sha256:" + oracles.SANDBOX_POLICY_SHA256,
    }
    if set(runtime) != set(expected_runtime) or any(
        runtime.get(key) != expected for key, expected in expected_runtime.items()
    ):
        raise GrammarStdlibOracleError("oracle runner runtime identity drift")
    if value["status"] == "ok":
        if value["failure"] is not None:
            raise GrammarStdlibOracleError("successful oracle result carries a failure")
        if mode == "source" and (
            value["endpoint"].get("name") is not None or expected_ir is not None
        ):
            raise GrammarStdlibOracleError("source mode result has endpoint IR")
        if mode == "endpoint" and (
            value["endpoint"].get("count") != 1
            or expected_ir is None
            or (
                requested_endpoint is not None
                and value["endpoint"].get("name") != requested_endpoint
            )
        ):
            raise GrammarStdlibOracleError("endpoint mode result has no unique IR")
    elif expected_ir is not None or not isinstance(value["failure"], dict):
        raise GrammarStdlibOracleError("invalid oracle result has inconsistent failure evidence")
    return value


def _external_checkout_identity(metis_root: Path) -> tuple[str, str, str]:
    """Capture the only external state this helper is permitted to observe."""

    return (
        str(catalog_pin._run_git(metis_root, "status", "--porcelain=v1", "--untracked-files=no")),
        str(catalog_pin._run_git(metis_root, "rev-parse", "HEAD")),
        str(catalog_pin._run_git(metis_root, "rev-parse", "HEAD^{tree}")),
    )


def _tooling_sha256(tooling: Path) -> str:
    """Hash archived tooling, deliberately excluding its separately-pinned runtime.

    ``node_modules`` can contain links and is covered by the existing pinned
    dependency-tree hash.  Every other archived tooling path, including empty
    directories, contributes to this digest so a session cannot hide a write
    to compiler source behind a successful individual request.
    """

    digest = hashlib.sha256()
    try:
        paths = sorted(tooling.rglob("*"), key=lambda item: item.relative_to(tooling).as_posix())
    except OSError as error:
        raise GrammarStdlibOracleError("isolated tooling is unavailable") from error
    for path in paths:
        relative = path.relative_to(tooling)
        if relative.parts and relative.parts[0] == "node_modules":
            continue
        encoded = relative.as_posix().encode("utf-8")
        try:
            if path.is_symlink():
                digest.update(b"L\0" + encoded + b"\0" + os.readlink(path).encode("utf-8") + b"\0")
            elif path.is_file():
                digest.update(b"F\0" + encoded + b"\0")
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                digest.update(b"\0")
            elif path.is_dir():
                digest.update(b"D\0" + encoded + b"\0")
            else:
                raise GrammarStdlibOracleError("isolated tooling contains a special file")
        except OSError as error:
            raise GrammarStdlibOracleError("isolated tooling changed while it was read") from error
    return "sha256:" + digest.hexdigest()


def _filesystem_stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    """Return only the metadata fields bound by the session filesystem contract."""

    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _filesystem_identity_roster(root: Path, label: str) -> tuple[tuple[object, ...], ...]:
    """Return a bounded, deterministic metadata identity for an immutable tree.

    The session uses this inexpensive roster around every oracle request.  It is
    deliberately not a content hash: entry and exit retain the full tooling and
    dependency hashes.  ``lstat`` metadata makes persistent writes, restored
    mtimes, replacement, link changes, and directory membership changes visible
    without rereading every dependency payload for every request.
    """

    rows: list[tuple[object, ...]] = []

    def stable_lstat(path: Path) -> os.stat_result:
        try:
            return path.lstat()
        except OSError as error:
            raise GrammarStdlibOracleError(f"{label} is unavailable") from error

    def append(path: Path, relative: str) -> None:
        if len(rows) >= MAX_SESSION_FILESYSTEM_ENTRIES:
            raise GrammarStdlibOracleError(f"{label} exceeds the filesystem entry bound")
        before_stat = stable_lstat(path)
        before = _filesystem_stat_identity(before_stat)
        mode = before_stat.st_mode
        if stat.S_ISREG(mode):
            kind = "file"
            target: str | None = None
        elif stat.S_ISDIR(mode):
            kind = "directory"
            target = None
        elif stat.S_ISLNK(mode):
            kind = "symlink"
            try:
                target = os.readlink(path)
            except OSError as error:
                raise GrammarStdlibOracleError(f"{label} changed while it was read") from error
        else:
            raise GrammarStdlibOracleError(f"{label} contains a special file")

        rows.append(
            (
                relative,
                kind,
                *before,
                target,
            )
        )
        if kind != "directory":
            if _filesystem_stat_identity(stable_lstat(path)) != before:
                raise GrammarStdlibOracleError(f"{label} changed while it was read")
            return

        try:
            with os.scandir(path) as stream:
                children = sorted(stream, key=lambda entry: entry.name)
        except OSError as error:
            raise GrammarStdlibOracleError(f"{label} is unavailable") from error
        if len(rows) + len(children) > MAX_SESSION_FILESYSTEM_ENTRIES:
            raise GrammarStdlibOracleError(f"{label} exceeds the filesystem entry bound")
        for child in children:
            child_relative = child.name if relative == "." else f"{relative}/{child.name}"
            append(Path(child.path), child_relative)
        if _filesystem_stat_identity(stable_lstat(path)) != before:
            raise GrammarStdlibOracleError(f"{label} changed while it was read")

    append(root, ".")
    return tuple(rows)


def _request(
    *,
    source: str,
    filename: str,
    execution_mode: str,
    endpoint: str | None,
    workspace_sources: Mapping[str, str] | None,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    source = _safe_source(source, "source")
    filename = _safe_filename(filename, "filename")
    if execution_mode not in {"source", "endpoint"}:
        raise GrammarStdlibOracleError("execution_mode must be source or endpoint")
    if endpoint is not None and (
        not isinstance(endpoint, str) or not endpoint or len(endpoint) > 256
    ):
        raise GrammarStdlibOracleError("endpoint must be null or a bounded non-empty string")
    if execution_mode == "source" and endpoint is not None:
        raise GrammarStdlibOracleError("source execution_mode requires a null endpoint")
    return {
        "schema_version": 1,
        "source": source,
        "filename": filename,
        "execution_mode": execution_mode,
        "endpoint": endpoint,
        "metis_root": f"snapshot://{identity['revision']}/{identity['tree']}",
        "metis_revision": identity["revision"],
        "metis_tree": identity["tree"],
        "workspace_sources": _workspace(workspace_sources, filename),
    }


class GrammarStdlibOracleSession:
    """One short-lived, pinned archive session for several oracle requests.

    Entering validates the grammar/stdlib and catalog pins once, materializes
    one archive snapshot, and installs the runner once.  ``run`` accepts the
    exact caller-controlled request fields of :func:`run_grammar_stdlib_oracle`.
    It never exposes source text in its returned canonical envelope.
    """

    def __init__(self, *, metis_root: Path, node_path: Path) -> None:
        self._metis_root = Path(metis_root)
        self._node_path = Path(node_path)
        self._snapshot_context: Any | None = None
        self._snapshot: refresh._Snapshot | None = None
        self._runner: Path | None = None
        self._loader: Path | None = None
        self._pin_identity: dict[str, Any] | None = None
        self._identity: dict[str, Any] | None = None
        self._external_identity: tuple[str, str, str] | None = None
        self._modules_sha256: str | None = None
        self._tooling_sha256: str | None = None
        self._filesystem_roster: tuple[tuple[object, ...], ...] | None = None
        self._snapshot_policy_sha256: str | None = None
        self._entered = False
        self._poisoned = False

    @property
    def pin_identity(self) -> Mapping[str, Any]:
        """The validated pin identity for this active session."""

        if self._pin_identity is None:
            raise GrammarStdlibOracleError("oracle session is not active")
        return self._pin_identity

    def __enter__(self) -> GrammarStdlibOracleSession:
        if self._entered:
            raise GrammarStdlibOracleError("oracle session cannot be entered twice")
        self._entered = True
        try:
            self._pin_identity = validate_grammar_stdlib_pin(metis_root=self._metis_root)
            base = catalog_pin.load_catalog_maintenance_pin()
            evidence_by_id = {item["id"]: item for item in base["evidence"]}
            runtime = {
                "node_version": base["runtime"]["node_version"],
                "node_sha256": base["runtime"]["node_sha256"],
                "package_sha256": evidence_by_id["tooling_package"]["sha256"],
                "lock_sha256": evidence_by_id["tooling_lock"]["sha256"],
                "node_modules_sha256": base["runtime"]["node_modules_sha256"],
            }
            self._identity = {
                "revision": base["revision"],
                "tree": base["tree"],
                "runtime": runtime,
            }
            self._external_identity = _external_checkout_identity(self._metis_root)
            snapshot_context = refresh._pinned_snapshot(self._metis_root, self._node_path)
            self._snapshot = snapshot_context.__enter__()
            self._snapshot_context = snapshot_context
            self._snapshot_policy_sha256 = _bytes_sha(self._snapshot.policy.encode("utf-8"))
            self._runner, self._loader = _install_runner(self._snapshot, self._identity)
            self._modules_sha256 = catalog_pin._node_modules_sha256(
                self._snapshot.tooling / "node_modules"
            )
            self._tooling_sha256 = _tooling_sha256(self._snapshot.tooling)
            self._filesystem_roster = _filesystem_identity_roster(
                self._snapshot.root, "isolated oracle snapshot"
            )
            return self
        except (
            catalog_pin.CatalogMaintenancePinError,
            refresh.CatalogRetrievalRefreshError,
        ) as error:
            self._close_snapshot(None, None, None)
            raise GrammarStdlibOracleError(str(error)) from error
        except BaseException:
            self._close_snapshot(None, None, None)
            raise

    def _assert_request_unchanged(self) -> None:
        if self._poisoned:
            raise GrammarStdlibOracleError("oracle session is poisoned after an identity drift")
        if (
            self._snapshot is None
            or self._filesystem_roster is None
            or self._external_identity is None
        ):
            raise GrammarStdlibOracleError("oracle session is not active")
        try:
            roster = _filesystem_identity_roster(self._snapshot.root, "isolated oracle snapshot")
            external_identity = _external_checkout_identity(self._metis_root)
        except (GrammarStdlibOracleError, catalog_pin.CatalogMaintenancePinError) as error:
            self._poisoned = True
            if isinstance(error, GrammarStdlibOracleError):
                raise
            raise GrammarStdlibOracleError(
                "oracle session identity cannot be revalidated"
            ) from error
        if roster != self._filesystem_roster:
            self._poisoned = True
            raise GrammarStdlibOracleError(
                "oracle runner modified the isolated snapshot filesystem"
            )
        if external_identity != self._external_identity:
            self._poisoned = True
            raise GrammarStdlibOracleError("oracle execution changed the external Metis checkout")

    def _assert_final_unchanged(self) -> None:
        if (
            self._snapshot is None
            or self._modules_sha256 is None
            or self._tooling_sha256 is None
            or self._external_identity is None
        ):
            raise GrammarStdlibOracleError("oracle session is not active")
        try:
            modules_sha256 = catalog_pin._node_modules_sha256(
                self._snapshot.tooling / "node_modules"
            )
            tooling_sha256 = _tooling_sha256(self._snapshot.tooling)
            external_identity = _external_checkout_identity(self._metis_root)
        except (GrammarStdlibOracleError, catalog_pin.CatalogMaintenancePinError) as error:
            self._poisoned = True
            if isinstance(error, GrammarStdlibOracleError):
                raise
            raise GrammarStdlibOracleError(
                "oracle session identity cannot be revalidated"
            ) from error
        if modules_sha256 != self._modules_sha256.removeprefix("sha256:"):
            self._poisoned = True
            raise GrammarStdlibOracleError("oracle runner modified the isolated tooling runtime")
        if tooling_sha256 != self._tooling_sha256:
            self._poisoned = True
            raise GrammarStdlibOracleError("oracle runner modified isolated tooling")
        if external_identity != self._external_identity:
            self._poisoned = True
            raise GrammarStdlibOracleError("oracle execution changed the external Metis checkout")

    def _close_snapshot(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        context = self._snapshot_context
        self._snapshot_context = None
        self._snapshot = None
        self._runner = None
        self._loader = None
        self._filesystem_roster = None
        if context is not None:
            context.__exit__(exc_type, exc, traceback)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> bool:
        request_identity_error: BaseException | None = None
        try:
            try:
                self._assert_request_unchanged()
            except BaseException as error:
                request_identity_error = error
            self._assert_final_unchanged()
            if request_identity_error is not None:
                raise request_identity_error
        finally:
            self._close_snapshot(exc_type, exc, traceback)
        return False

    def run(
        self,
        *,
        source: str,
        filename: str,
        execution_mode: str = "source",
        endpoint: str | None = None,
        workspace_sources: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Evaluate one bounded request inside this session's immutable snapshot."""

        if (
            self._snapshot is None
            or self._runner is None
            or self._loader is None
            or self._identity is None
            or self._pin_identity is None
            or self._snapshot_policy_sha256 is None
        ):
            raise GrammarStdlibOracleError("oracle session is not active")
        if self._poisoned:
            raise GrammarStdlibOracleError("oracle session is poisoned after an identity drift")
        request = _request(
            source=source,
            filename=filename,
            execution_mode=execution_mode,
            endpoint=endpoint,
            workspace_sources=workspace_sources,
            identity=self._identity,
        )
        runtime = self._identity["runtime"]
        command = [
            str(self._snapshot.node),
            *oracles.LOADER_FLAGS,
            str(self._loader),
            str(self._runner),
            "--metis-root",
            str(self._snapshot.root),
            "--metis-revision",
            self._identity["revision"],
            "--metis-tree",
            self._identity["tree"],
            "--tooling-package-sha256",
            runtime["package_sha256"].removeprefix("sha256:"),
            "--tooling-lock-sha256",
            runtime["lock_sha256"].removeprefix("sha256:"),
            "--node-modules-sha256",
            runtime["node_modules_sha256"].removeprefix("sha256:"),
            "--runner-sha256",
            oracles.PINNED_RUNNER_SHA256,
            "--loader-sha256",
            oracles.PINNED_LOADER_SHA256,
            "--node-binary-sha256",
            runtime["node_sha256"].removeprefix("sha256:"),
            "--oracle-policy-version",
            oracles.SANDBOX_POLICY_VERSION,
            "--oracle-policy-sha256",
            oracles.SANDBOX_POLICY_SHA256,
            "--execution-policy-sha256",
            oracles.SANDBOX_POLICY_SHA256,
            "--snapshot-identity",
            request["metis_root"],
            "--runtime-node-path",
            oracles.NODE_RUNTIME_IDENTITY,
            "--node-actual-path",
            str(self._snapshot.node.resolve()),
            "--runtime-loader-path",
            f"snapshot://{self._identity['revision']}/{self._identity['tree']}/.metis-oracle/native_ts_loader.mjs",
            "--runtime-loader-flags",
            json.dumps(list(oracles.LOADER_FLAGS), separators=(",", ":")),
            "--runtime-runner-path",
            f"snapshot://{self._identity['revision']}/{self._identity['tree']}/.metis-oracle/runner.ts",
            "--runner-actual-path",
            str(self._runner),
            "--loader-path",
            str(self._loader),
        ]
        self._assert_request_unchanged()
        try:
            try:
                completed = subprocess.run(
                    [str(catalog_pin.SANDBOX_EXEC), "-p", self._snapshot.policy, *command],
                    cwd=self._snapshot.tooling,
                    input=_canonical(request),
                    capture_output=True,
                    timeout=catalog_pin.PROBE_TIMEOUT_SECONDS,
                    check=False,
                    env=catalog_pin._probe_process_environment(),
                )
            except OSError as error:
                raise GrammarStdlibOracleError("oracle runner could not be executed") from error
            if len(completed.stdout) > MAX_STDOUT_BYTES or len(completed.stderr) > MAX_STDERR_BYTES:
                raise GrammarStdlibOracleError("oracle runner output exceeds its byte cap")
            if completed.returncode != 0:
                raise GrammarStdlibOracleError(
                    "oracle runner failed: "
                    f"returncode={completed.returncode} stderr={_bytes_sha(completed.stderr)}"
                )
            try:
                result = json.loads(completed.stdout.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise GrammarStdlibOracleError("oracle runner emitted invalid JSON") from error
            if completed.stdout != _canonical(result):
                raise GrammarStdlibOracleError("oracle runner output is not canonical JSON")
            result = _validated_result(
                result,
                identity=self._identity,
                mode=execution_mode,
                requested_endpoint=endpoint,
            )
        finally:
            self._assert_request_unchanged()
        evidence = {
            "request_sha256": _sha(request),
            "diagnostics_sha256": _sha(result["diagnostics"]),
            "ast_sha256": _sha(result["ast"]["inventory"]),
            "ir_sha256": None if result["ir"]["value"] is None else _sha(result["ir"]["value"]),
            "runtime_sha256": _sha(result["runtime"]),
            "stdout_sha256": _bytes_sha(completed.stdout),
            "stderr_sha256": _bytes_sha(completed.stderr),
            "snapshot_sandbox_policy_sha256": self._snapshot_policy_sha256,
            "archive_snapshot": True,
            "network_denied": True,
            "writes_denied": True,
            "external_checkout_changed": False,
        }
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "status": result["status"],
            "pin": self._pin_identity,
            "result": result,
            "evidence": evidence,
        }
        envelope["evidence"]["envelope_sha256"] = _sha(envelope)
        return envelope


@contextmanager
def grammar_stdlib_oracle_session(
    *, metis_root: Path, node_path: Path
) -> Iterator[GrammarStdlibOracleSession]:
    """Open one fail-closed session for multiple grammar/stdlib oracle requests."""

    with GrammarStdlibOracleSession(metis_root=metis_root, node_path=node_path) as session:
        yield session


def run_grammar_stdlib_oracle(
    *,
    metis_root: Path,
    node_path: Path,
    source: str,
    filename: str,
    execution_mode: str = "source",
    endpoint: str | None = None,
    workspace_sources: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run a caller-supplied grammar/stdlib source in a pinned archive snapshot.

    No result is written to the Model 1 worktree.  The returned object is
    canonical evidence only; it contains no caller source text, tenant file, or
    model output.
    """

    _safe_source(source, "source")
    safe_filename = _safe_filename(filename, "filename")
    if execution_mode not in {"source", "endpoint"}:
        raise GrammarStdlibOracleError("execution_mode must be source or endpoint")
    if endpoint is not None and (
        not isinstance(endpoint, str) or not endpoint or len(endpoint) > 256
    ):
        raise GrammarStdlibOracleError("endpoint must be null or a bounded non-empty string")
    if execution_mode == "source" and endpoint is not None:
        raise GrammarStdlibOracleError("source execution_mode requires a null endpoint")
    _workspace(workspace_sources, safe_filename)
    with grammar_stdlib_oracle_session(metis_root=metis_root, node_path=node_path) as session:
        return session.run(
            source=source,
            filename=filename,
            execution_mode=execution_mode,
            endpoint=endpoint,
            workspace_sources=workspace_sources,
        )
