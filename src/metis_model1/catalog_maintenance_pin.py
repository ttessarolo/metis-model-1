"""Executable, Git-object-bound verifier for the catalog maintenance pin.

The historical Oracle pin remains immutable.  This module verifies the later
catalog-domain implementation from committed Git objects and runs its bounded
offline probes from an archive, never from mutable working-tree source files.
The result is deliberately scoped to a cooperative local host: this verifier
does not claim resistance to a concurrent hostile process running as the same
user.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

from metis_model1.oracles import _node_modules_sha256

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "schemas/catalog-maintenance-pin.schema.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/catalog-maintenance-pin-v1.json"
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
GIT_EXECUTABLE = Path("/usr/bin/git")
REMOTE_GIT_CWD = Path("/private/var/empty")
GIT_VERSION = "git version 2.50.1 (Apple Git-155)"
GIT_BYTES = 118640
GIT_LINKS = 78
GIT_SHA256 = "sha256:b8763cf250e607a778bb4603cecb5b90338814d0a3dfcba0d57b1de242f610e9"
MAX_STDOUT_BYTES = 4 * 1024 * 1024
MAX_STDERR_BYTES = 128 * 1024
PROBE_TIMEOUT_SECONDS = 120
MAX_CONTRACT_BYTES = 2 * 1024 * 1024
SCHEMA_FILE_SHA256 = "sha256:3a0d70e142f92cae42497ca62402fcffa72c5efd4a7a25f995a1d5434273c01a"
MANIFEST_FILE_SHA256 = "sha256:04c8dff417b14bbc08bc291e8d6de0039a958d08f7f4ac8fc2e99a671fc902ea"

EXPECTED_EVIDENCE_PATHS = {
    "specification": "docs/design/catalog-values/spec.md",
    "retrieval_contract": "docs/design/catalog-values/retrieval-api.md",
    "grammar": "tooling/src/language/metis.langium",
    "generated_ast": "tooling/src/language/generated/ast.ts",
    "domain_resolver": "tooling/src/language/field-values.ts",
    "validator": "tooling/src/language/metis-validator.ts",
    "tenant_threshold_setting_keys": "tooling/src/language/settings-schema.ts",
    "language_compiler_bridge": "tooling/src/language/metis-compile.ts",
    "compiler": "tooling/src/compiler/compile.ts",
    "ir_contract": "tooling/src/compiler/ir.ts",
    "catalog_sync": "tooling/src/cli/catalog-sync-values.ts",
    "retrieval_cli": "tooling/src/cli/catalog-domain.ts",
    "surface_oracle": "tooling/test/catalog-values-surface.ts",
    "sync_oracle": "tooling/test/catalog-sync-values-rewrite.ts",
    "editor_oracle": "tooling/test/catalog-values-tree.ts",
    "retrieval_oracle": "tooling/test/catalog-domain.ts",
    "tooling_package": "tooling/package.json",
    "tooling_lock": "tooling/package-lock.json",
}

EXPECTED_PROBES = {
    "typecheck": (
        "node",
        "node_modules/typescript/bin/tsc",
        "--noEmit",
        "-p",
        "tsconfig.probes.json",
    ),
    "catalog_surface": ("node", "--import", "tsx", "test/catalog-values-surface.ts"),
    "catalog_sync": ("node", "--import", "tsx", "test/catalog-sync-values-rewrite.ts"),
    "catalog_tree": ("node", "--import", "tsx", "test/catalog-values-tree.ts"),
    "catalog_retrieval": ("node", "--import", "tsx", "test/catalog-domain.ts"),
}


class CatalogMaintenancePinError(ValueError):
    """Raised when the catalog implementation cannot satisfy its fixed pin."""


def _canonical(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise CatalogMaintenancePinError(f"pin is not canonical JSON: {error}") from error
    return rendered.encode("utf-8")


def manifest_sha256(manifest: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(manifest)).hexdigest()


def _load_json(path: Path, label: str) -> Any:
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        if opened.st_size > MAX_CONTRACT_BYTES:
            raise CatalogMaintenancePinError(f"{label} exceeds the contract size cap")
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
        path_after = path.lstat()
    except OSError as error:
        raise CatalogMaintenancePinError(f"{label} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity = lambda value: (  # noqa: E731 - compact immutable stat identity
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(path_after)
        or len(raw) != before.st_size
    ):
        raise CatalogMaintenancePinError(f"{label} is not a stable regular file")
    expected_sha256 = {
        SCHEMA_PATH.name: SCHEMA_FILE_SHA256,
        MANIFEST_PATH.name: MANIFEST_FILE_SHA256,
    }.get(path.name)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if expected_sha256 is None or digest != expected_sha256:
        raise CatalogMaintenancePinError(f"{label} differs from its fixed file digest")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogMaintenancePinError(f"{label} is not valid JSON") from error


def load_catalog_maintenance_pin(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = root.resolve(strict=True)
    schema = _load_json(root / SCHEMA_PATH.relative_to(PROJECT_ROOT), "pin schema")
    manifest = _load_json(root / MANIFEST_PATH.relative_to(PROJECT_ROOT), "pin manifest")
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:  # noqa: BLE001 - schema failures must close the gate
        raise CatalogMaintenancePinError(f"pin schema is invalid: {error}") from error
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise CatalogMaintenancePinError(f"pin schema mismatch at {location}: {first.message}")
    if not isinstance(manifest, dict):
        raise CatalogMaintenancePinError("pin manifest must be an object")
    return manifest


def validate_catalog_maintenance_pin_contract(root: Path = PROJECT_ROOT) -> list[str]:
    """Validate the tracked pin and its exact evidence/probe rosters."""

    try:
        manifest = load_catalog_maintenance_pin(root)
        errors: list[str] = []
        evidence = manifest["evidence"]
        ids = [item["id"] for item in evidence]
        paths = [item["path"] for item in evidence]
        blob_oids = [item["blob_oid"] for item in evidence]
        if len(ids) != len(set(ids)) or set(ids) != set(EXPECTED_EVIDENCE_PATHS):
            errors.append("catalog pin evidence IDs are not the exact registered roster")
        if len(paths) != len(set(paths)):
            errors.append("catalog pin evidence paths are not distinct")
        if len(blob_oids) != len(set(blob_oids)):
            errors.append("catalog pin evidence blob OIDs are not distinct")
        for item in evidence:
            expected_path = EXPECTED_EVIDENCE_PATHS.get(item["id"])
            if expected_path is not None and item["path"] != expected_path:
                errors.append(f"catalog pin evidence path drift for {item['id']}")
            _safe_relative_path(item["path"], f"evidence {item['id']}")

        probes = manifest["probes"]
        probe_ids = [item["id"] for item in probes]
        if len(probe_ids) != len(set(probe_ids)) or set(probe_ids) != set(EXPECTED_PROBES):
            errors.append("catalog pin probe IDs are not the exact registered roster")
        for probe in probes:
            expected_argv = EXPECTED_PROBES.get(probe["id"])
            if expected_argv is not None and tuple(probe["argv"]) != expected_argv:
                errors.append(f"catalog pin probe argv drift for {probe['id']}")
        return errors
    except CatalogMaintenancePinError as error:
        return [str(error)]


def _safe_relative_path(value: str, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CatalogMaintenancePinError(f"{label} is not a relative POSIX path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
        or any(part == ".git" for part in relative.parts)
    ):
        raise CatalogMaintenancePinError(f"{label} path is forbidden")
    return relative


def _git_process_environment() -> dict[str, str]:
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_COUNT": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_CEILING_DIRECTORIES": str(REMOTE_GIT_CWD),
    }
    # Preserve only the user's existing SSH trust/agent roots. Git and command
    # override variables remain absent, and executables are resolved from the
    # fixed system PATH above.
    for name in ("HOME", "SSH_AUTH_SOCK"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _verify_remote_git_cwd() -> None:
    """Require a root-owned, non-repository cwd for detached remote checks."""

    try:
        status = REMOTE_GIT_CWD.lstat()
    except OSError as error:
        raise CatalogMaintenancePinError("detached Git cwd is unavailable") from error
    if (
        not stat.S_ISDIR(status.st_mode)
        or status.st_uid != 0
        or status.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or (REMOTE_GIT_CWD / ".git").exists()
    ):
        raise CatalogMaintenancePinError("detached Git cwd is not a protected directory")


def _probe_process_environment() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
    }


def _verify_git_executable() -> None:
    try:
        before = GIT_EXECUTABLE.stat()
        raw = GIT_EXECUTABLE.read_bytes()
        after = GIT_EXECUTABLE.stat()
    except OSError as error:
        raise CatalogMaintenancePinError("pinned Git executable is unavailable") from error
    identity = lambda value: (  # noqa: E731 - compact immutable stat identity
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if (
        not stat.S_ISREG(before.st_mode)
        or identity(before) != identity(after)
        or before.st_nlink != GIT_LINKS
        or len(raw) != GIT_BYTES
        or "sha256:" + hashlib.sha256(raw).hexdigest() != GIT_SHA256
    ):
        raise CatalogMaintenancePinError("Git executable differs from its fixed pin")
    try:
        version = subprocess.run(
            [str(GIT_EXECUTABLE), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            env=_git_process_environment(),
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise CatalogMaintenancePinError("cannot execute the pinned Git binary") from error
    if version != GIT_VERSION:
        raise CatalogMaintenancePinError("Git version differs from its fixed pin")


def _run_git(repository: Path | None, *args: str, text: bool = True) -> str | bytes:
    _verify_git_executable()
    command = [str(GIT_EXECUTABLE)]
    cwd: Path | None = None
    if repository is not None:
        command.extend(("-C", str(repository)))
    else:
        _verify_remote_git_cwd()
        cwd = REMOTE_GIT_CWD
    command.extend(args)
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=text,
            timeout=30,
            env=_git_process_environment(),
            cwd=cwd,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CatalogMaintenancePinError(f"Git verification failed for {' '.join(args)}") from error
    if text:
        return completed.stdout.strip()
    return completed.stdout


def _verify_node(node_path: Path, runtime: dict[str, Any]) -> bytes:
    try:
        node = node_path.resolve(strict=True)
        descriptor = os.open(
            node,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as error:
        raise CatalogMaintenancePinError("pinned Node binary is unavailable") from error
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    except OSError as error:
        raise CatalogMaintenancePinError("cannot read the pinned Node binary") from error
    finally:
        os.close(descriptor)
    identity = lambda value: (  # noqa: E731 - compact immutable stat identity
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    raw = b"".join(chunks)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o755
        or before.st_nlink != 1
        or identity(before) != identity(after)
        or len(raw) != runtime["node_bytes"]
        or "sha256:" + hashlib.sha256(raw).hexdigest() != runtime["node_sha256"]
    ):
        raise CatalogMaintenancePinError("Node binary differs from the catalog pin")
    return raw


def _safe_extract_archive(raw: bytes, destination: Path) -> None:
    archive_path = destination / "metis.tar"
    archive_path.write_bytes(raw)
    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            members = archive.getmembers()
            for member in members:
                relative = _safe_relative_path(member.name.rstrip("/"), "Git archive member")
                if not (member.isdir() or member.isfile()):
                    raise CatalogMaintenancePinError(
                        f"Git archive member is not a directory or regular file: {relative}"
                    )
            archive.extractall(destination, members=members)  # noqa: S202 - roster checked above
    except (OSError, tarfile.TarError) as error:
        raise CatalogMaintenancePinError("cannot extract the pinned Git archive") from error
    finally:
        archive_path.unlink(missing_ok=True)


def _sandbox_policy(snapshot: Path) -> str:
    home = Path.home().resolve(strict=True)
    return " ".join(
        (
            "(version 1)",
            "(allow default)",
            "(deny file-write*)",
            "(deny network*)",
            f"(deny file-read* (subpath {json.dumps(str(home))}))",
            f"(allow file-read* (subpath {json.dumps(str(snapshot))}))",
        )
    )


def _assert_sandbox_boundaries(directory: Path, policy: str) -> None:
    if not SANDBOX_EXEC.is_file():
        raise CatalogMaintenancePinError("sandbox-exec is required for catalog probes")
    canary = directory / "forbidden-write-canary"
    try:
        completed = subprocess.run(
            [str(SANDBOX_EXEC), "-p", policy, "/usr/bin/touch", str(canary)],
            check=False,
            capture_output=True,
            timeout=10,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CatalogMaintenancePinError("cannot execute the sandbox write canary") from error
    if completed.returncode == 0 or canary.exists():
        raise CatalogMaintenancePinError("catalog probe sandbox does not deny file writes")
    readable_host_canary = PROJECT_ROOT / "pyproject.toml"
    try:
        read_attempt = subprocess.run(
            [str(SANDBOX_EXEC), "-p", policy, "/bin/cat", str(readable_host_canary)],
            check=False,
            capture_output=True,
            timeout=10,
            env=_probe_process_environment(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CatalogMaintenancePinError("cannot execute the sandbox read canary") from error
    if read_attempt.returncode == 0:
        raise CatalogMaintenancePinError("catalog probe sandbox does not deny host-home reads")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            network_attempt = subprocess.run(
                [
                    str(SANDBOX_EXEC),
                    "-p",
                    policy,
                    "/usr/bin/nc",
                    "-z",
                    "-w",
                    "1",
                    "127.0.0.1",
                    str(port),
                ],
                check=False,
                capture_output=True,
                timeout=10,
                env=_probe_process_environment(),
            )
    except (OSError, subprocess.SubprocessError) as error:
        raise CatalogMaintenancePinError("cannot execute the sandbox network canary") from error
    if network_attempt.returncode == 0:
        raise CatalogMaintenancePinError("catalog probe sandbox does not deny loopback network")


def _run_archive_probes(
    manifest: dict[str, Any],
    metis_root: Path,
    node_bytes: bytes,
) -> list[dict[str, Any]]:
    try:
        archive = _run_git(
            metis_root,
            "archive",
            "--format=tar",
            manifest["revision"],
            "tooling",
            text=False,
        )
        assert isinstance(archive, bytes)
        with tempfile.TemporaryDirectory(prefix="metis-model1-catalog-pin-") as temp:
            snapshot = Path(temp)
            _safe_extract_archive(archive, snapshot)
            tooling = snapshot / "tooling"
            source_modules = (metis_root / "tooling/node_modules").resolve(strict=True)
            snapshot_modules = tooling / "node_modules"
            shutil.copytree(source_modules, snapshot_modules, symlinks=True)
            modules_before = _node_modules_sha256(snapshot_modules)
            if "sha256:" + modules_before != manifest["runtime"]["node_modules_sha256"]:
                raise CatalogMaintenancePinError(
                    "copied tooling node_modules differs from the catalog pin"
                )
            node = snapshot / "pinned-node"
            node.write_bytes(node_bytes)
            node.chmod(0o500)
            policy = _sandbox_policy(snapshot)
            _assert_sandbox_boundaries(snapshot, policy)
            version = subprocess.run(
                [str(SANDBOX_EXEC), "-p", policy, str(node), "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
                env=_probe_process_environment(),
            ).stdout.strip()
            if version != manifest["runtime"]["node_version"]:
                raise CatalogMaintenancePinError("copied Node version differs from the catalog pin")
            reports: list[dict[str, Any]] = []
            for probe in manifest["probes"]:
                argv = [str(node), *probe["argv"][1:]]
                completed = subprocess.run(
                    [str(SANDBOX_EXEC), "-p", policy, *argv],
                    cwd=tooling,
                    check=False,
                    capture_output=True,
                    timeout=PROBE_TIMEOUT_SECONDS,
                    env=_probe_process_environment(),
                )
                if len(completed.stdout) > MAX_STDOUT_BYTES:
                    raise CatalogMaintenancePinError(f"probe stdout cap exceeded: {probe['id']}")
                if len(completed.stderr) > MAX_STDERR_BYTES:
                    raise CatalogMaintenancePinError(f"probe stderr cap exceeded: {probe['id']}")
                stdout = completed.stdout.decode("utf-8", errors="strict")
                marker = probe["success_marker"]
                if completed.returncode != 0 or (marker is not None and marker not in stdout):
                    raise CatalogMaintenancePinError(f"catalog probe failed: {probe['id']}")
                reports.append(
                    {
                        "id": probe["id"],
                        "exit_code": completed.returncode,
                        "stdout_sha256": "sha256:" + hashlib.sha256(completed.stdout).hexdigest(),
                        "stderr_sha256": "sha256:" + hashlib.sha256(completed.stderr).hexdigest(),
                    }
                )
            modules_after = _node_modules_sha256(snapshot_modules)
            if modules_after != modules_before:
                raise CatalogMaintenancePinError("catalog probes changed copied node_modules")
            return reports
    except (OSError, UnicodeDecodeError, subprocess.SubprocessError) as error:
        if isinstance(error, CatalogMaintenancePinError):
            raise
        raise CatalogMaintenancePinError("catalog archive probe execution failed") from error


def verify_catalog_maintenance_pin(
    metis_root: Path,
    node_path: Path,
) -> dict[str, Any]:
    """Verify Git objects, runtime, and bounded offline probes for the pin."""

    contract_errors = validate_catalog_maintenance_pin_contract()
    if contract_errors:
        raise CatalogMaintenancePinError("; ".join(contract_errors))
    manifest = load_catalog_maintenance_pin()
    metis = metis_root.resolve(strict=True)
    if not metis.is_dir():
        raise CatalogMaintenancePinError("Metis root must be a directory")

    revision = manifest["revision"]
    if _run_git(metis, "rev-parse", revision) != revision:
        raise CatalogMaintenancePinError("Metis repository lacks the catalog pin commit")
    if _run_git(metis, "rev-parse", f"{revision}^{{tree}}") != manifest["tree"]:
        raise CatalogMaintenancePinError("Metis pinned tree differs from the catalog pin")
    _run_git(metis, "merge-base", "--is-ancestor", manifest["surface_revision"], revision)

    def verify_remote_contains_revision() -> str:
        remote = _run_git(
            None,
            "ls-remote",
            manifest["remote_url"],
            manifest["remote_ref"],
        )
        rows = [line.split() for line in str(remote).splitlines() if line.strip()]
        if (
            len(rows) != 1
            or len(rows[0]) != 2
            or rows[0][1] != manifest["remote_ref"]
            or len(rows[0][0]) != 40
            or any(character not in "0123456789abcdef" for character in rows[0][0])
        ):
            raise CatalogMaintenancePinError("live Metis remote ref is not one commit")
        remote_revision = rows[0][0]
        try:
            _run_git(metis, "merge-base", "--is-ancestor", revision, remote_revision)
        except CatalogMaintenancePinError as error:
            raise CatalogMaintenancePinError(
                "live Metis remote ref does not contain the catalog pin"
            ) from error
        return remote_revision

    remote_revision_before = verify_remote_contains_revision()

    verified_evidence: list[dict[str, str]] = []
    for item in manifest["evidence"]:
        path = item["path"]
        record = str(_run_git(metis, "ls-tree", revision, "--", path)).split()
        if len(record) != 4 or record[0] != "100644" or record[1] != "blob":
            raise CatalogMaintenancePinError(
                f"catalog evidence is not one regular Git blob: {path}"
            )
        if record[2] != item["blob_oid"] or record[3] != path:
            raise CatalogMaintenancePinError(f"catalog evidence Git identity drift: {path}")
        raw = _run_git(metis, "cat-file", "blob", item["blob_oid"], text=False)
        assert isinstance(raw, bytes)
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        if digest != item["sha256"]:
            raise CatalogMaintenancePinError(f"catalog evidence content drift: {path}")
        verified_evidence.append({"id": item["id"], "path": path, "sha256": digest})

    package = json.loads(
        _run_git(metis, "cat-file", "blob", f"{revision}:tooling/package.json", text=False)
    )
    lock = json.loads(
        _run_git(metis, "cat-file", "blob", f"{revision}:tooling/package-lock.json", text=False)
    )
    if (
        package.get("version") != manifest["tooling_version"]
        or lock.get("version") != manifest["tooling_version"]
        or lock.get("packages", {}).get("", {}).get("version") != manifest["tooling_version"]
    ):
        raise CatalogMaintenancePinError("tooling package and lock versions are inconsistent")

    node_bytes = _verify_node(node_path, manifest["runtime"])
    probe_reports = _run_archive_probes(manifest, metis, node_bytes)
    if (
        _run_git(metis, "rev-parse", revision) != revision
        or _run_git(metis, "rev-parse", f"{revision}^{{tree}}") != manifest["tree"]
    ):
        raise CatalogMaintenancePinError("Metis pinned Git objects changed during verification")
    remote_revision_after = verify_remote_contains_revision()
    if remote_revision_after != remote_revision_before:
        raise CatalogMaintenancePinError("live Metis remote ref changed during verification")

    return {
        "status": "verified_local_cooperative",
        "authority_scope": "cooperative_host_exact_git_objects_and_sandboxed_probes",
        "pin_id": manifest["pin_id"],
        "revision": revision,
        "tree": manifest["tree"],
        "remote_ref_contains_revision_verified": True,
        "remote_ref_revision": remote_revision_after,
        "evidence_in": len(manifest["evidence"]),
        "evidence_out": len(verified_evidence),
        "evidence_distinct": len({item["id"] for item in verified_evidence}),
        "evidence_gaps": len(manifest["evidence"]) - len(verified_evidence),
        "probes_in": len(manifest["probes"]),
        "probes_out": len(probe_reports),
        "probe_reports": probe_reports,
        "manifest_sha256": manifest_sha256(manifest),
        "nonclaims": [
            *manifest["nonclaims"],
            "not_same_uid_adversary_resistant",
            "not_general_untrusted_code_sandbox",
        ],
    }
