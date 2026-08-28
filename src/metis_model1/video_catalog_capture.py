"""Offline capture of one pinned Metis schema-2 semantic catalog projection.

The capture is deliberately read-only.  It invokes only the pinned
``catalog-domain.ts`` describe/values entry point, validates every response
through the existing strict consumer, and returns the joined projection in
memory.  Public evidence is limited to identities, counts and hashes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from metis_model1 import catalog_maintenance_pin as legacy_pin
from metis_model1.catalog_semantic_retrieval import (
    MAX_RESPONSE_BYTES,
    CatalogSemanticRetrievalError,
    adapt_catalog_semantic_response,
    validate_catalog_semantic_receipt,
)
from metis_model1.video_catalog_projection import (
    FINITE_KINDS,
    VideoCatalogProjectionError,
    build_catalog_semantic_projection,
    validate_catalog_projection_receipt,
)
from metis_model1.video_semantic_toolchain_pin import (
    load_video_semantic_toolchain_pin,
    manifest_sha256,
)

CAPTURE_CONTRACT = "metis-model1/video-catalog-capture-v1"
CAPTURE_RECEIPT_ID = "video-semantics/catalog-capture-receipt-v1"
COMMAND_TIMEOUT_SECONDS = 30
MAX_STDERR_BYTES = 64 * 1024
MAX_NODE_BYTES = 512 * 1024 * 1024
MAX_COMMANDS = 100_001
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class VideoCatalogCaptureError(RuntimeError):
    """Payload-free failure from the offline capture boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes = b""


Runner = Callable[..., CommandResult]
RuntimeVerifier = Callable[[Path, Path, Mapping[str, Any]], None]


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
        raise VideoCatalogCaptureError("CAPTURE_NOT_CANONICAL") from error


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _value_sha256(value: Any) -> str:
    return _sha256(_canonical(value))


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            [
                "/usr/bin/git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.sshCommand=:",
                "--no-optional-locks",
                *args,
            ],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_SYSTEM": "/dev/null",
            },
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise VideoCatalogCaptureError("GIT_IDENTITY_UNAVAILABLE") from error
    if (
        completed.returncode != 0
        or len(completed.stdout) > MAX_STDERR_BYTES
        or len(completed.stderr) > MAX_STDERR_BYTES
    ):
        raise VideoCatalogCaptureError("GIT_IDENTITY_UNAVAILABLE")
    try:
        return completed.stdout.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as error:
        raise VideoCatalogCaptureError("GIT_IDENTITY_UNAVAILABLE") from error


def _verify_checkout(
    root: Path, revision: str, tree: str, *, label: str, reject_ignored: bool = False
) -> None:
    if not root.is_dir() or not _OID_RE.fullmatch(revision) or not _OID_RE.fullmatch(tree):
        raise VideoCatalogCaptureError(f"{label}_IDENTITY_INVALID")
    if _git(root, "rev-parse", "HEAD") != revision:
        raise VideoCatalogCaptureError(f"{label}_COMMIT_DRIFT")
    if _git(root, "rev-parse", "HEAD^{tree}") != tree:
        raise VideoCatalogCaptureError(f"{label}_TREE_DRIFT")
    status = _git(root, "status", "--porcelain=v1", "--ignored=matching", "--untracked-files=all")
    lines = status.splitlines()
    if reject_ignored and any(line.startswith("!! ") for line in lines):
        raise VideoCatalogCaptureError(f"{label}_IGNORED_FILES_PRESENT")
    if any(not line.startswith("!! ") for line in lines):
        raise VideoCatalogCaptureError(f"{label}_TRACKED_WORKTREE_DIRTY")


def _read_pinned_binary(node: Path) -> bytes:
    """Read one owned binary through an O_NOFOLLOW descriptor with a size cap."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    getuid = getattr(os, "getuid", None)
    if nofollow is None or not callable(getuid):
        raise VideoCatalogCaptureError("TOOLCHAIN_RUNTIME_UNAVAILABLE")
    descriptor: int | None = None
    try:
        # O_NONBLOCK makes a FIFO/device fail closed at open time instead of
        # allowing an attacker-controlled special file to stall the capture.
        descriptor = os.open(node, os.O_RDONLY | nofollow | cloexec | nonblock)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != int(getuid())
            or info.st_size < 0
            or info.st_size > MAX_NODE_BYTES
        ):
            raise VideoCatalogCaptureError("TOOLCHAIN_RUNTIME_UNAVAILABLE")
        output = bytearray()
        while len(output) <= MAX_NODE_BYTES:
            chunk = os.read(descriptor, min(1024 * 1024, MAX_NODE_BYTES + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or after.st_uid != int(getuid())
            or after.st_size != info.st_size
            or len(output) != after.st_size
        ):
            raise VideoCatalogCaptureError("TOOLCHAIN_RUNTIME_UNAVAILABLE")
        return bytes(output)
    except OSError as error:
        raise VideoCatalogCaptureError("TOOLCHAIN_RUNTIME_UNAVAILABLE") from error
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)


def _verify_runtime(node: Path, metis_root: Path, runtime: Mapping[str, Any]) -> None:
    try:
        raw = _read_pinned_binary(node)
        modules = (metis_root / "tooling" / "node_modules").resolve(strict=True)
    except VideoCatalogCaptureError:
        raise
    except OSError as error:
        raise VideoCatalogCaptureError("TOOLCHAIN_RUNTIME_UNAVAILABLE") from error
    if (
        len(raw) != runtime.get("node_bytes")
        or _sha256(raw) != runtime.get("node_sha256")
        or "sha256:" + legacy_pin._node_modules_sha256(modules)
        != runtime.get("node_modules_sha256")
    ):
        raise VideoCatalogCaptureError("TOOLCHAIN_RUNTIME_DRIFT")


def _sandbox_profile(
    metis_root: Path,
    tenant_root: Path,
    node_path: Path,
    tenant_inputs: Sequence[Path],
) -> str:
    metis_root = metis_root.resolve(strict=True)
    tenant_root = tenant_root.resolve(strict=True)
    node_realpath = node_path.resolve(strict=True)
    tooling = metis_root / "tooling"
    tenant_paths = [Path(path).resolve(strict=True) for path in tenant_inputs]
    directory_literals = {
        ancestor
        for path in (metis_root, tenant_root, node_realpath, tooling, *tenant_paths)
        for ancestor in path.parents
    }
    allowed = [
        "(allow process-fork)",
        "(allow sysctl-read)",
        f"(allow process-exec (literal {json.dumps(str(node_path))}))",
        f"(allow process-exec (literal {json.dumps(str(node_realpath))}))",
        # Node's dynamic loader reads only these system/runtime locations.
        # User files remain denied unless they are listed below explicitly.
        '(allow file-read* (subpath "/usr/bin"))',
        '(allow file-read* (subpath "/usr/lib"))',
        '(allow file-read* (subpath "/usr/share"))',
        '(allow file-read* (subpath "/usr/sbin"))',
        '(allow file-read* (subpath "/System/Library"))',
        '(allow file-read* (subpath "/Library/Frameworks"))',
        '(allow file-read* (subpath "/private/var/db"))',
        '(allow file-read* (literal "/dev/null"))',
        '(allow file-read* (literal "/dev/urandom"))',
        '(allow file-read* (literal "/dev/random"))',
        *(
            f"(allow file-read* (literal {json.dumps(str(path))}))"
            for path in sorted(directory_literals, key=str)
        ),
        f"(deny file-read* (subpath {json.dumps(str(metis_root))}))",
        f"(deny file-read* (subpath {json.dumps(str(tenant_root))}))",
        f"(allow file-read* (literal {json.dumps(str(tooling))}))",
        f"(allow file-read* (subpath {json.dumps(str(tooling / 'src'))}))",
        f"(allow file-read* (subpath {json.dumps(str(tooling / 'node_modules'))}))",
        f"(allow file-read* (literal {json.dumps(str(tooling / 'package.json'))}))",
        f"(allow file-read* (literal {json.dumps(str(node_path))}))",
        f"(allow file-read* (literal {json.dumps(str(node_realpath))}))",
        *(f"(allow file-read* (literal {json.dumps(str(path))}))" for path in tenant_paths),
    ]
    return " ".join(
        (
            "(version 1)",
            "(deny default)",
            "(deny network*)",
            "(deny file-write*)",
            *allowed,
        )
    )


def _default_runner(
    *, argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: int
) -> CommandResult:
    sandbox = Path("/usr/bin/sandbox-exec")
    if not sandbox.is_file():
        raise VideoCatalogCaptureError("OFFLINE_SANDBOX_UNAVAILABLE")
    profile = env.get("METIS_CAPTURE_SANDBOX_PROFILE")
    if not profile:
        raise VideoCatalogCaptureError("OFFLINE_SANDBOX_UNAVAILABLE")
    process_env = {
        key: value for key, value in env.items() if key != "METIS_CAPTURE_SANDBOX_PROFILE"
    }
    try:
        completed = subprocess.run(
            [str(sandbox), "-p", profile, *argv],
            cwd=cwd,
            check=False,
            capture_output=True,
            timeout=timeout,
            env=process_env,
        )
    except subprocess.TimeoutExpired as error:
        raise VideoCatalogCaptureError("TOOLCHAIN_COMMAND_TIMEOUT") from error
    except OSError as error:
        raise VideoCatalogCaptureError("TOOLCHAIN_COMMAND_UNAVAILABLE") from error
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _tenant_input_paths(root: Path) -> list[Path]:
    """Return only tracked inputs read by ``loadTenantContext``/``loadTenantDocs``."""
    raw = _git(root, "ls-files", "-z", "--", "metis.toml", "*.metis")
    # NUL is the path separator for ``git ls-files -z``; use the roster only
    # after the status check has proved the checkout has no untracked/ignored files.
    names = [item for item in raw.split("\x00") if item]
    if not names or any(
        not item or item.startswith(("/", "\\")) or "\\" in item or ".." in Path(item).parts
        for item in names
    ):
        raise VideoCatalogCaptureError("TENANT_INPUT_ROSTER_INVALID")
    paths = [root / item for item in names]
    for path in paths:
        try:
            resolved = path.resolve(strict=True)
            relative = resolved.relative_to(root)
        except (OSError, ValueError) as error:
            raise VideoCatalogCaptureError("TENANT_INPUT_ROSTER_INVALID") from error
        if relative != Path("metis.toml") and relative.suffix != ".metis":
            raise VideoCatalogCaptureError("TENANT_INPUT_ROSTER_INVALID")
        info = path.lstat()
        if resolved != path or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise VideoCatalogCaptureError("TENANT_INPUT_ROSTER_INVALID")
    return paths


def _run(
    runner: Runner,
    *,
    argv: tuple[str, ...],
    cwd: Path,
    env: Mapping[str, str],
) -> bytes:
    try:
        result = runner(argv=argv, cwd=cwd, env=env, timeout=COMMAND_TIMEOUT_SECONDS)
    except VideoCatalogCaptureError:
        raise
    except Exception as error:
        raise VideoCatalogCaptureError("TOOLCHAIN_COMMAND_FAILED") from error
    if not isinstance(result, CommandResult):
        raise VideoCatalogCaptureError("TOOLCHAIN_RUNNER_INVALID")
    if (
        type(result.returncode) is not int
        or not isinstance(result.stdout, bytes)
        or not isinstance(result.stderr, bytes)
    ):
        raise VideoCatalogCaptureError("TOOLCHAIN_RUNNER_INVALID")
    if len(result.stdout) > MAX_RESPONSE_BYTES or len(result.stderr) > MAX_STDERR_BYTES:
        raise VideoCatalogCaptureError("TOOLCHAIN_OUTPUT_CAP_EXCEEDED")
    if result.returncode != 0:
        raise VideoCatalogCaptureError("TOOLCHAIN_COMMAND_FAILED")
    return result.stdout


def _finite_fields(describe: Mapping[str, Any]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []

    def walk(catalog: str, roster: Sequence[Any], parent: str | None = None) -> None:
        for raw in roster:
            name = raw["name"]
            path = name if parent is None else f"{parent}.{name}"
            domain = raw["domain"]
            if domain["kind"] in FINITE_KINDS and domain.get("size", 0) > 0:
                fields.append((catalog, path))
            children = raw.get("fields")
            if children is not None:
                walk(catalog, children, path)

    for catalog in describe["catalogs"]:
        walk(catalog["name"], catalog["fields"])
    if len(fields) + 1 > MAX_COMMANDS:
        raise VideoCatalogCaptureError("COMMAND_ROSTER_CAP_EXCEEDED")
    return sorted(fields)


def _receipt_hash(receipt: Mapping[str, Any]) -> str:
    return _value_sha256({key: value for key, value in receipt.items() if key != "receipt_sha256"})


def _capture_video_catalog_core(
    *,
    metis_root: Path,
    tenant_root: Path,
    node_path: Path,
    tenant_revision: str,
    tenant_tree: str,
    catalog_ref: str,
    runner: Runner | None = None,
    pin: Mapping[str, Any] | None = None,
    runtime_verifier: RuntimeVerifier | None = None,
) -> dict[str, Any]:
    """Capture and join one real tenant catalog without persistence or network."""

    try:
        metis = Path(metis_root).resolve(strict=True)
        tenant = Path(tenant_root).resolve(strict=True)
        node_input = Path(node_path)
        if stat.S_ISLNK(node_input.lstat().st_mode):
            raise VideoCatalogCaptureError("TOOLCHAIN_RUNTIME_UNAVAILABLE")
        node = node_input.resolve(strict=True)
    except OSError as error:
        raise VideoCatalogCaptureError("CAPTURE_PATH_UNAVAILABLE") from error
    manifest = dict(pin) if pin is not None else load_video_semantic_toolchain_pin()
    required = {"revision", "tree", "retrieval_schema", "runtime"}
    if not required.issubset(manifest) or manifest.get("retrieval_schema") != 2:
        raise VideoCatalogCaptureError("TOOLCHAIN_PIN_INVALID")
    revision = manifest["revision"]
    tree = manifest["tree"]
    if (
        not isinstance(revision, str)
        or not isinstance(tree, str)
        or not isinstance(catalog_ref, str)
        or not catalog_ref
        or len(catalog_ref) > 256
        or catalog_ref.startswith("-")
        or "/" in catalog_ref
        or "\\" in catalog_ref
    ):
        raise VideoCatalogCaptureError("CAPTURE_QUERY_INVALID")
    _verify_checkout(metis, revision, tree, label="TOOLCHAIN")
    _verify_checkout(tenant, tenant_revision, tenant_tree, label="TENANT", reject_ignored=True)
    tenant_inputs = _tenant_input_paths(tenant)
    verifier = runtime_verifier or _verify_runtime
    try:
        verifier(node, metis, manifest["runtime"])
    except VideoCatalogCaptureError:
        raise
    except Exception as error:
        raise VideoCatalogCaptureError("TOOLCHAIN_RUNTIME_DRIFT") from error

    tooling = metis / "tooling"
    entrypoint = "src/cli/catalog-domain.ts"
    process_env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "HOME": "/dev/null",
        "TMPDIR": "/tmp",
        "METIS_CAPTURE_SANDBOX_PROFILE": _sandbox_profile(metis, tenant, node, tenant_inputs),
    }
    injected_runner = runner is not None
    execute = runner or _default_runner
    describe_argv = (
        str(node),
        "--import",
        "tsx",
        entrypoint,
        "describe",
        "--tenant",
        str(tenant),
        "--catalog",
        catalog_ref,
        "--semantic",
    )
    describe_raw = _run(execute, argv=describe_argv, cwd=tooling, env=process_env)
    try:
        describe_result = adapt_catalog_semantic_response(
            "describe", describe_raw, catalog=catalog_ref
        )
    except CatalogSemanticRetrievalError as error:
        raise VideoCatalogCaptureError("DESCRIBE_PAYLOAD_INVALID") from error
    if validate_catalog_semantic_receipt(
        describe_result.receipt, query=describe_result.receipt["query"]
    ):
        raise VideoCatalogCaptureError("DESCRIBE_RECEIPT_INVALID")

    finite = _finite_fields(describe_result.projection)
    values_projections: list[dict[str, Any]] = []
    values_receipts: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = [
        {
            "operation": "describe",
            "catalog": catalog_ref,
            "field": None,
            "argv": list(describe_argv),
        }
    ]
    observed: set[tuple[str, str]] = set()
    for catalog, field in finite:
        argv = (
            str(node),
            "--import",
            "tsx",
            entrypoint,
            "values",
            "--tenant",
            str(tenant),
            "--catalog",
            catalog,
            "--field",
            field,
            "--semantic",
        )
        raw = _run(execute, argv=argv, cwd=tooling, env=process_env)
        try:
            result = adapt_catalog_semantic_response("values", raw, catalog=catalog, field=field)
        except CatalogSemanticRetrievalError as error:
            raise VideoCatalogCaptureError("VALUES_PAYLOAD_INVALID") from error
        if validate_catalog_semantic_receipt(result.receipt, query=result.receipt["query"]):
            raise VideoCatalogCaptureError("VALUES_RECEIPT_INVALID")
        identity = (result.projection["catalog"], result.projection["field"])
        if identity in observed:
            raise VideoCatalogCaptureError("VALUES_ROSTER_DUPLICATE")
        observed.add(identity)
        values_projections.append(result.projection)
        values_receipts.append(result.receipt)
        commands.append(
            {"operation": "values", "catalog": catalog, "field": field, "argv": list(argv)}
        )
    if observed != set(finite):
        raise VideoCatalogCaptureError("VALUES_ROSTER_INCOMPLETE")

    try:
        joined = build_catalog_semantic_projection(
            describe_result.projection, values_projections, catalog_ref=catalog_ref
        )
    except VideoCatalogProjectionError as error:
        raise VideoCatalogCaptureError("PROJECTION_JOIN_INVALID") from error
    if validate_catalog_projection_receipt(joined["receipt"]):
        raise VideoCatalogCaptureError("PROJECTION_RECEIPT_INVALID")

    # Recheck both preimages after all commands to close commit/worktree races.
    _verify_checkout(metis, revision, tree, label="TOOLCHAIN")
    _verify_checkout(tenant, tenant_revision, tenant_tree, label="TENANT")
    value_receipt_hashes = sorted(item["receipt_sha256"] for item in values_receipts)
    counts = joined["receipt"]["counts"]
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_id": CAPTURE_RECEIPT_ID,
        "pin": {
            "manifest_sha256": manifest_sha256(manifest),
            "toolchain_revision": revision,
            "toolchain_tree": tree,
            "retrieval_schema": 2,
        },
        "tenant": {"revision": tenant_revision, "tree": tenant_tree},
        "counts": {
            "commands_in": len(commands),
            "commands_out": len(commands),
            "commands_distinct": len({_value_sha256(item) for item in commands}),
            "commands_gaps": 0,
            "catalogs": counts["catalogs"],
            "fields": counts["fields"],
            "finite_fields": len(finite),
            "values_responses": len(values_projections),
            "values": counts["values"],
        },
        "hashes": {
            "projection_sha256": joined["receipt"]["projection_sha256"],
            "describe_receipt_sha256": describe_result.receipt["receipt_sha256"],
            "values_receipts_sha256": _value_sha256(value_receipt_hashes),
            "command_roster_sha256": _value_sha256(commands),
        },
        "policy": {
            "execution_boundary": "injected-test-runner" if injected_runner else "sandbox-exec",
            "network_denied": not injected_runner,
            "tenant_writes_denied": not injected_runner,
            "sync_executed": False,
            "payload_redacted": True,
            "persisted": False,
        },
    }
    receipt["receipt_sha256"] = _receipt_hash(receipt)
    return {
        "capture_contract": CAPTURE_CONTRACT,
        "projection": joined["projection"],
        "commands": commands,
        "source_receipts": {
            "describe": describe_result.receipt,
            "values": values_receipts,
            "projection": joined["receipt"],
        },
        "receipt": receipt,
    }


def capture_video_catalog(
    *,
    metis_root: Path,
    tenant_root: Path,
    node_path: Path,
    tenant_revision: str,
    tenant_tree: str,
    catalog_ref: str,
    pin: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture through the production path, which cannot inject a runner."""
    return _capture_video_catalog_core(
        metis_root=metis_root,
        tenant_root=tenant_root,
        node_path=node_path,
        tenant_revision=tenant_revision,
        tenant_tree=tenant_tree,
        catalog_ref=catalog_ref,
        pin=pin,
    )


def _capture_video_catalog_for_test(
    *,
    metis_root: Path,
    tenant_root: Path,
    node_path: Path,
    tenant_revision: str,
    tenant_tree: str,
    catalog_ref: str,
    runner: Runner,
    pin: Mapping[str, Any] | None = None,
    runtime_verifier: RuntimeVerifier | None = None,
) -> dict[str, Any]:
    """Private test seam; never use this wrapper in production code."""
    return _capture_video_catalog_core(
        metis_root=metis_root,
        tenant_root=tenant_root,
        node_path=node_path,
        tenant_revision=tenant_revision,
        tenant_tree=tenant_tree,
        catalog_ref=catalog_ref,
        runner=runner,
        pin=pin,
        runtime_verifier=runtime_verifier,
    )


def validate_video_catalog_capture_receipt(receipt: Any) -> list[str]:
    """Validate the payload-free capture receipt."""

    try:
        if not isinstance(receipt, Mapping) or set(receipt) != {
            "schema_version",
            "receipt_id",
            "pin",
            "tenant",
            "counts",
            "hashes",
            "policy",
            "receipt_sha256",
        }:
            raise VideoCatalogCaptureError("CAPTURE_RECEIPT_FIELDS_INVALID")
        if receipt.get("schema_version") != 1 or receipt.get("receipt_id") != CAPTURE_RECEIPT_ID:
            raise VideoCatalogCaptureError("CAPTURE_RECEIPT_IDENTITY_INVALID")
        pin = receipt.get("pin")
        if (
            not isinstance(pin, Mapping)
            or set(pin)
            != {"manifest_sha256", "toolchain_revision", "toolchain_tree", "retrieval_schema"}
            or pin.get("retrieval_schema") != 2
        ):
            raise VideoCatalogCaptureError("CAPTURE_RECEIPT_PIN_INVALID")
        if (
            not _SHA256_RE.fullmatch(str(pin.get("manifest_sha256", "")))
            or not _OID_RE.fullmatch(str(pin.get("toolchain_revision", "")))
            or not _OID_RE.fullmatch(str(pin.get("toolchain_tree", "")))
        ):
            raise VideoCatalogCaptureError("CAPTURE_RECEIPT_PIN_INVALID")
        tenant = receipt.get("tenant")
        if (
            not isinstance(tenant, Mapping)
            or set(tenant) != {"revision", "tree"}
            or not all(_OID_RE.fullmatch(str(tenant.get(key, ""))) for key in ("revision", "tree"))
        ):
            raise VideoCatalogCaptureError("CAPTURE_RECEIPT_TENANT_INVALID")
        counts = receipt.get("counts")
        expected_counts = {
            "commands_in",
            "commands_out",
            "commands_distinct",
            "commands_gaps",
            "catalogs",
            "fields",
            "finite_fields",
            "values_responses",
            "values",
        }
        if (
            not isinstance(counts, Mapping)
            or set(counts) != expected_counts
            or any(type(value) is not int or value < 0 for value in counts.values())
        ):
            raise VideoCatalogCaptureError("CAPTURE_RECEIPT_COUNTS_INVALID")
        if (
            counts["commands_gaps"] != 0
            or counts["commands_in"] != counts["commands_out"]
            or counts["commands_in"] != counts["commands_distinct"]
            or counts["commands_in"] != counts["values_responses"] + 1
            or counts["finite_fields"] != counts["values_responses"]
        ):
            raise VideoCatalogCaptureError("CAPTURE_RECEIPT_ROSTER_INVALID")
        hashes = receipt.get("hashes")
        if (
            not isinstance(hashes, Mapping)
            or set(hashes)
            != {
                "projection_sha256",
                "describe_receipt_sha256",
                "values_receipts_sha256",
                "command_roster_sha256",
            }
            or any(not _SHA256_RE.fullmatch(str(value)) for value in hashes.values())
        ):
            raise VideoCatalogCaptureError("CAPTURE_RECEIPT_HASHES_INVALID")
        policy = receipt.get("policy")
        fixed_policy = {
            "sync_executed": False,
            "payload_redacted": True,
            "persisted": False,
        }
        if (
            not isinstance(policy, Mapping)
            or set(policy)
            != {
                "execution_boundary",
                "network_denied",
                "tenant_writes_denied",
                *fixed_policy,
            }
            or any(policy.get(key) != value for key, value in fixed_policy.items())
        ):
            raise VideoCatalogCaptureError("CAPTURE_RECEIPT_POLICY_INVALID")
        boundary = policy.get("execution_boundary")
        if boundary == "sandbox-exec":
            if (
                policy.get("network_denied") is not True
                or policy.get("tenant_writes_denied") is not True
            ):
                raise VideoCatalogCaptureError("CAPTURE_RECEIPT_POLICY_INVALID")
        elif boundary == "injected-test-runner":
            if (
                policy.get("network_denied") is not False
                or policy.get("tenant_writes_denied") is not False
            ):
                raise VideoCatalogCaptureError("CAPTURE_RECEIPT_POLICY_INVALID")
        else:
            raise VideoCatalogCaptureError("CAPTURE_RECEIPT_POLICY_INVALID")
        if not _SHA256_RE.fullmatch(str(receipt.get("receipt_sha256", ""))) or receipt[
            "receipt_sha256"
        ] != _receipt_hash(receipt):
            raise VideoCatalogCaptureError("CAPTURE_RECEIPT_HASH_INVALID")
        forbidden = {"catalog", "field", "literal", "means", "aka", "label", "text", "argv"}
        stack: list[Any] = [receipt]
        while stack:
            current = stack.pop()
            if isinstance(current, Mapping):
                if any(key in forbidden for key in current):
                    raise VideoCatalogCaptureError("CAPTURE_RECEIPT_PAYLOAD_PRESENT")
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)
        return []
    except (VideoCatalogCaptureError, TypeError, ValueError) as error:
        return [str(error)]


__all__ = [
    "CAPTURE_CONTRACT",
    "CAPTURE_RECEIPT_ID",
    "COMMAND_TIMEOUT_SECONDS",
    "CommandResult",
    "VideoCatalogCaptureError",
    "capture_video_catalog",
    "validate_video_catalog_capture_receipt",
]
