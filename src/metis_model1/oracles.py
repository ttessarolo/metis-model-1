"""Fail-closed bridge to the pinned, read-only Metis compiler.

The bridge deliberately keeps the compiler process outside this Python
package.  It sends one canonical JSON request to the TypeScript runner and
stores one canonical evidence envelope in a caller-supplied path outside the
Metis checkout.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

PINNED_METIS_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
PINNED_METIS_TREE = "75473e26deff4084a0eb077a4c3e27d52dc07998"
PINNED_NODE_VERSION = "v22.22.3"
PINNED_TOOLING_PACKAGE_SHA256 = "f8130a67f948720b339695fae614f32185610f762d69b85ff600f08971f2fb80"
PINNED_TOOLING_LOCK_SHA256 = "fed109b62f300ed824201f4b167d700072008b0b4a817cbb512a2eee32edc9fb"
PINNED_NODE_MODULES_SHA256 = "1cea5f2f0371d3c57b9ef9787707bc1079f88dc697c7be2c6c247e4018f6e463"
PINNED_RUNNER_SHA256 = "8278504a71c2d609aa441a0e81537c92de28d329453a6a99bba2b43afc0aefe0"
PINNED_NODE_BINARY_SHA256 = "5d9d3872911e2340a43b707962e68143de8a4e8d54628845c0c4f2de1fb7cd5c"
NODE_RUNTIME_IDENTITY = "node://v22.22.3"
NODE_RUNTIME_ENV = "METIS_MODEL1_NODE"
SANDBOX_EXEC_PATH = Path("/usr/bin/sandbox-exec")
SANDBOX_EXEC_IDENTITY = "sandbox-exec:///usr/bin/sandbox-exec"
SANDBOX_POLICY = "(version 1) (allow default) (deny file-write*)"
SANDBOX_POLICY_SHA256 = "ee5178deb85dee0799f1042397133c362211fa1d6e302ffcf9b82e68cb035540"
SANDBOX_POLICY_VERSION = "1"
STERILE_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
LANGUAGE_VERSION = "0.43"
SCHEMA_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = (PROJECT_ROOT / "artifacts").resolve()
RUNNER_PATH = (PROJECT_ROOT / "runtime/metis_oracle/runner.ts").resolve()
SCHEMA_PATH = PROJECT_ROOT / "schemas/oracle-result.schema.json"


class OracleError(ValueError):
    """Raised when an oracle result cannot be trusted."""


MetisOracleError = OracleError


def _canonical(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise OracleError(f"oracle evidence is not canonical JSON: {error}") from error
    return rendered.encode()


def _sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_sandbox_policy() -> None:
    """Require the registered deny-write sandbox and prove it denies a canary."""

    if (
        not SANDBOX_EXEC_PATH.is_file()
        or not os.access(SANDBOX_EXEC_PATH, os.X_OK)
        or hashlib.sha256(SANDBOX_POLICY.encode()).hexdigest() != SANDBOX_POLICY_SHA256
    ):
        raise OracleError("registered sandbox-exec policy is unavailable")
    try:
        probe = subprocess.run(
            [str(SANDBOX_EXEC_PATH), "-p", SANDBOX_POLICY, "/usr/bin/true"],
            env=STERILE_ENV,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OracleError(f"cannot start registered sandbox-exec policy: {error}") from error
    if probe.returncode != 0:
        raise OracleError("registered sandbox-exec policy failed its harmless probe")
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    canary_dir = Path(tempfile.mkdtemp(prefix="metis-oracle-sandbox-canary-", dir=ARTIFACT_ROOT))
    canary = canary_dir / "write-denied"
    try:
        command = f"printf x > {shlex.quote(str(canary))}"
        try:
            attempt = subprocess.run(
                [str(SANDBOX_EXEC_PATH), "-p", SANDBOX_POLICY, "/bin/sh", "-c", command],
                env=STERILE_ENV,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise OracleError(f"cannot execute sandbox write canary: {error}") from error
        if attempt.returncode == 0 or canary.exists():
            raise OracleError("registered sandbox-exec policy failed to deny file writes")
    finally:
        shutil.rmtree(canary_dir, ignore_errors=True)


def _validate_node_binary(node: str | os.PathLike[str] | None) -> tuple[Path, str]:
    if node is None:
        raise OracleError(
            f"node runtime mismatch: expected {PINNED_NODE_VERSION}, node was not found on PATH"
        )
    try:
        resolved = Path(node).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise OracleError("pinned Node binary path is invalid") from error
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise OracleError("pinned Node binary must be an executable file")
    digest = _file_sha256(resolved)
    if digest != PINNED_NODE_BINARY_SHA256:
        raise OracleError("node runtime mismatch: Node binary hash differs from its pin")
    # Never execute this mutable source path. It is copied into the isolated
    # snapshot and re-hashed before sandboxed execution; the runner then reports
    # ``process.version``, which the response validator binds to the version pin.
    return resolved, digest


def _resolve_pinned_node() -> tuple[Path, str]:
    """Resolve only the registered Node binary, independent of PATH order."""

    configured = os.environ.get(NODE_RUNTIME_ENV)
    if configured is not None:
        if not configured or not Path(configured).is_absolute():
            raise OracleError(f"{NODE_RUNTIME_ENV} must be an absolute executable path")
        try:
            return _validate_node_binary(configured)
        except OSError as error:
            raise OracleError(f"cannot read {NODE_RUNTIME_ENV} binary") from error

    seen: set[Path] = set()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / "node"
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved in seen or not resolved.is_file() or not os.access(resolved, os.X_OK):
            continue
        seen.add(resolved)
        try:
            return _validate_node_binary(resolved)
        except (OSError, OracleError):
            continue
    raise OracleError(
        f"node runtime mismatch: no {PINNED_NODE_VERSION} binary matching the registered hash"
    )


def _node_modules_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        if path.is_symlink():
            digest.update(b"L\0" + relative + b"\0" + os.readlink(path).encode() + b"\0")
        elif path.is_file():
            digest.update(b"F\0" + relative + b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
    value = digest.hexdigest()
    return value


def _validate_tree_symlinks(root: Path, label: str) -> None:
    """Reject links which could make the isolated runner reach outside root."""

    root = root.resolve()
    for path in root.rglob("*"):
        if path.is_symlink() and not _contains(root, path.resolve(strict=False)):
            raise OracleError(f"{label} contains a symlink escaping its root: {path}")


def _build_isolated_snapshot(
    root: Path,
    revision: str,
    tree: str,
    tooling_runtime: dict[str, str],
    runner: Path,
    node_binary: Path,
) -> tuple[tempfile.TemporaryDirectory[str], Path, Path, Path, Path]:
    """Materialize only pinned Git objects plus a checked tooling dependency copy."""

    holder: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory(
        prefix="metis-oracle-snapshot-"
    )
    snapshot = Path(holder.name)
    archive = snapshot.with_name(f"{snapshot.name}.tar")
    try:
        with archive.open("wb") as stream:
            completed = subprocess.run(
                ["git", "-C", str(root), "archive", "--format=tar", revision],
                check=True,
                stdout=stream,
                stderr=subprocess.PIPE,
                timeout=30,
                text=False,
            )
        del completed
        with archive.open("rb") as stream, tarfile.open(fileobj=stream, mode="r:") as bundle:
            # ``data`` prevents absolute and traversal members on supported Python versions.
            bundle.extractall(snapshot, filter="data")
    except (OSError, subprocess.SubprocessError, tarfile.TarError, ValueError) as error:
        holder.cleanup()
        raise OracleError(f"cannot materialize the pinned Metis snapshot: {error}") from error
    finally:
        archive.unlink(missing_ok=True)

    tooling = snapshot / "tooling"
    source_modules = root / "tooling" / "node_modules"
    snapshot_modules = tooling / "node_modules"
    snapshot_runner = snapshot / ".metis-oracle" / "runner.ts"
    snapshot_node = snapshot / ".metis-oracle" / "node"
    try:
        if not tooling.is_dir():
            raise OracleError("pinned snapshot is missing tooling")
        shutil.copytree(source_modules, snapshot_modules, symlinks=True)
        snapshot_runner.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(runner, snapshot_runner)
        shutil.copyfile(node_binary, snapshot_node)
        shutil.copymode(node_binary, snapshot_node)
        if _file_sha256(snapshot_runner) != PINNED_RUNNER_SHA256:
            raise OracleError("isolated runner differs from its pin")
        if _file_sha256(snapshot_node) != PINNED_NODE_BINARY_SHA256:
            raise OracleError("isolated Node binary differs from its pin")
        _validate_tree_symlinks(snapshot, "Metis snapshot")
        if _file_sha256(tooling / "package.json") != tooling_runtime["package_sha256"]:
            raise OracleError("snapshot tooling package.json differs from its pin")
        if _file_sha256(tooling / "package-lock.json") != tooling_runtime["lock_sha256"]:
            raise OracleError("snapshot tooling package-lock.json differs from its pin")
        if _node_modules_sha256(snapshot_modules) != tooling_runtime["node_modules_sha256"]:
            raise OracleError("snapshot node_modules differs from its pin")
        identity = {
            "revision": revision,
            "tree": tree,
            "package_sha256": tooling_runtime["package_sha256"],
            "lock_sha256": tooling_runtime["lock_sha256"],
            "node_modules_sha256": tooling_runtime["node_modules_sha256"],
            "runner_sha256": PINNED_RUNNER_SHA256,
            "node_binary_sha256": PINNED_NODE_BINARY_SHA256,
            "sandbox_exec_path": SANDBOX_EXEC_IDENTITY,
            "sandbox_policy_version": SANDBOX_POLICY_VERSION,
            "sandbox_policy_sha256": SANDBOX_POLICY_SHA256,
        }
        (snapshot / ".metis-oracle-identity.json").write_bytes(_canonical(identity))
    except (OSError, shutil.Error, OracleError) as error:
        holder.cleanup()
        raise OracleError(f"cannot prepare the isolated Metis tooling: {error}") from error
    return holder, snapshot, snapshot_modules, snapshot_runner, snapshot_node


def _resolve_absolute(path: str | os.PathLike[str], label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise OracleError(f"{label} must be absolute")
    return Path(os.path.abspath(candidate))


def _contains(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _reject_symlink_parents(path: Path, label: str) -> None:
    cursor = path.parent
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise OracleError(f"{label} parent contains a symlink")
        cursor = cursor.parent


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OracleError(f"cannot inspect Metis Git repository: {error}") from error
    return completed.stdout.strip()


def validate_pinned_metis(
    metis_root: str | os.PathLike[str],
    *,
    expected_revision: str = PINNED_METIS_REVISION,
) -> tuple[Path, str, str, dict[str, str]]:
    """Validate the repository identity and return root, revision and tree hash."""

    root = _resolve_absolute(metis_root, "metis_root").resolve(strict=True)
    if not root.is_dir():
        raise OracleError("metis_root must be an existing directory")
    if expected_revision != PINNED_METIS_REVISION:
        raise OracleError("overriding the pinned Metis revision is forbidden")
    revision = _git(root, "rev-parse", "HEAD")
    if revision != expected_revision:
        raise OracleError(f"Metis revision mismatch: expected {expected_revision}, got {revision}")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    if tree != PINNED_METIS_TREE:
        raise OracleError("Metis tree does not match the pinned toolchain tree")
    tracked = _git(root, "status", "--porcelain=v1", "--untracked-files=no")
    if tracked:
        raise OracleError("Metis tracked working tree must match the pinned revision")
    tooling = root / "tooling"
    tsx = tooling / "node_modules" / ".bin" / "tsx"
    if not tooling.is_dir() or not tsx.is_file() or not os.access(tsx, os.X_OK):
        raise OracleError("pinned tooling/node_modules/.bin/tsx is required")
    tsx_real = tsx.resolve(strict=True)
    node_modules = (tooling / "node_modules").resolve(strict=True)
    if not _contains(node_modules, tsx_real):
        raise OracleError("tsx must resolve inside pinned tooling/node_modules")
    package_sha256 = _file_sha256(tooling / "package.json")
    lock_sha256 = _file_sha256(tooling / "package-lock.json")
    modules_sha256 = _node_modules_sha256(node_modules)
    if package_sha256 != PINNED_TOOLING_PACKAGE_SHA256:
        raise OracleError("Metis tooling package.json differs from its pin")
    if lock_sha256 != PINNED_TOOLING_LOCK_SHA256:
        raise OracleError("Metis tooling package-lock.json differs from its pin")
    if modules_sha256 != PINNED_NODE_MODULES_SHA256:
        raise OracleError("Metis tooling node_modules differs from its pin")
    return (
        root,
        revision,
        tree,
        {
            "package_sha256": package_sha256,
            "lock_sha256": lock_sha256,
            "node_modules_sha256": modules_sha256,
        },
    )


def _validate_output_path(path: str | os.PathLike[str], metis_root: Path) -> Path:
    output = _resolve_absolute(path, "output_path")
    if output.suffix != ".json":
        raise OracleError("output_path must end in .json")
    if _contains(metis_root, output):
        raise OracleError("output_path may not be inside the Metis checkout")
    if not _contains(ARTIFACT_ROOT, output):
        raise OracleError("output_path must stay under the Model1 artifacts directory")
    _reject_symlink_parents(output, "output_path")
    if output.exists() and output.is_symlink():
        raise OracleError("output_path may not be a symlink")
    return output


def _validate_runner_path(path: str | os.PathLike[str], metis_root: Path) -> Path:
    runner = _resolve_absolute(path, "runner_path")
    if runner.suffix != ".ts" or not runner.is_file():
        raise OracleError("runner_path must be an existing TypeScript file")
    if _contains(metis_root, runner):
        raise OracleError("runner_path may not be inside the Metis checkout")
    _reject_symlink_parents(runner, "runner_path")
    if runner.is_symlink():
        raise OracleError("runner_path may not be a symlink")
    if runner.resolve() != RUNNER_PATH:
        raise OracleError("runner_path must be the pinned Model1 oracle runner")
    if _file_sha256(runner) != PINNED_RUNNER_SHA256:
        raise OracleError("oracle runner hash differs from its pin")
    return runner


def _runtime_identity_policy(
    revision: str, tree: str, tooling_runtime: dict[str, str] | None = None
) -> dict[str, str]:
    package_sha = PINNED_TOOLING_PACKAGE_SHA256
    lock_sha = PINNED_TOOLING_LOCK_SHA256
    modules_sha = PINNED_NODE_MODULES_SHA256
    if tooling_runtime is not None:
        package_sha = tooling_runtime["package_sha256"]
        lock_sha = tooling_runtime["lock_sha256"]
        modules_sha = tooling_runtime["node_modules_sha256"]
    return {
        "node": PINNED_NODE_VERSION,
        "node_path": NODE_RUNTIME_IDENTITY,
        "tsx_path": f"snapshot://{revision}/{tree}/tooling/node_modules/tsx/dist/loader.mjs",
        "runner_path": f"snapshot://{revision}/{tree}/.metis-oracle/runner.ts",
        "snapshot_revision": revision,
        "snapshot_tree": tree,
        "tooling_package_sha256": "sha256:" + package_sha,
        "tooling_lock_sha256": "sha256:" + lock_sha,
        "node_modules_sha256": "sha256:" + modules_sha,
        "node_binary_sha256": "sha256:" + PINNED_NODE_BINARY_SHA256,
        "sandbox_exec_path": SANDBOX_EXEC_IDENTITY,
        "sandbox_policy_version": SANDBOX_POLICY_VERSION,
        "sandbox_policy_sha256": "sha256:" + SANDBOX_POLICY_SHA256,
    }


def _runtime_identity(
    node_version: str,
    node_binary_sha256: str,
    revision: str,
    tree: str,
    tooling_runtime: dict[str, str],
) -> dict[str, str]:
    if node_version != PINNED_NODE_VERSION:
        raise OracleError(
            f"node runtime mismatch: expected {PINNED_NODE_VERSION}, got {node_version}"
        )
    if node_binary_sha256 != PINNED_NODE_BINARY_SHA256:
        raise OracleError("Node binary hash differs from its pin")
    identity = _runtime_identity_policy(revision, tree, tooling_runtime)
    identity["node"] = node_version
    return identity


def _check_response(
    result: Any,
    revision: str,
    tree: str,
    *,
    expected_runtime: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not isinstance(result, dict) or result.get("schema_version") != SCHEMA_VERSION:
        raise OracleError("runner returned an invalid schema version")
    if result.get("status") not in {"ok", "invalid"}:
        raise OracleError("runner returned an invalid status")
    if result.get("toolchain", {}).get("revision") != revision:
        raise OracleError("runner toolchain revision does not match pinned HEAD")
    if result.get("toolchain", {}).get("tree") != tree:
        raise OracleError("runner toolchain tree does not match pinned HEAD")
    if result.get("toolchain", {}).get("language_version") != LANGUAGE_VERSION:
        raise OracleError("runner language version does not match the registered contract")
    diagnostics = result.get("diagnostics")
    ast = result.get("ast")
    ir = result.get("ir")
    if not isinstance(diagnostics, dict) or not isinstance(ast, dict) or not isinstance(ir, dict):
        raise OracleError("runner omitted diagnostics, AST or IR evidence")
    if ast.get("signature") != _sha(ast.get("inventory")):
        raise OracleError("runner AST signature is not deterministic")
    ir_value = ir.get("value")
    expected_ir = None if ir_value is None else _sha(ir_value)
    if ir.get("signature") != expected_ir:
        raise OracleError("runner IR signature is not deterministic")
    endpoint = result.get("endpoint")
    failure = result.get("failure")
    result_runtime = result.get("runtime")
    if not isinstance(endpoint, dict):
        raise OracleError("runner omitted endpoint evidence")
    if not isinstance(result_runtime, dict) or result_runtime.get("node") != PINNED_NODE_VERSION:
        raise OracleError("runner runtime identity does not match the pin")
    if (
        result_runtime.get("snapshot_revision") != revision
        or result_runtime.get("snapshot_tree") != tree
        or result_runtime.get("tooling_package_sha256") != "sha256:" + PINNED_TOOLING_PACKAGE_SHA256
        or result_runtime.get("tooling_lock_sha256") != "sha256:" + PINNED_TOOLING_LOCK_SHA256
        or result_runtime.get("node_modules_sha256") != "sha256:" + PINNED_NODE_MODULES_SHA256
        or result_runtime.get("node_binary_sha256") != "sha256:" + PINNED_NODE_BINARY_SHA256
        or result_runtime.get("sandbox_exec_path") != SANDBOX_EXEC_IDENTITY
        or result_runtime.get("sandbox_policy_version") != SANDBOX_POLICY_VERSION
        or result_runtime.get("sandbox_policy_sha256") != "sha256:" + SANDBOX_POLICY_SHA256
    ):
        raise OracleError("runner runtime identity does not match the tooling pins")
    if expected_runtime is not None and result_runtime != expected_runtime:
        raise OracleError("runner runtime identity does not match the validated runtime")
    if result["status"] == "ok":
        validation_errors = [
            item
            for item in diagnostics.get("validation", [])
            if isinstance(item, dict) and item.get("severity") == 1
        ]
        if (
            failure is not None
            or ir_value is None
            or endpoint.get("count") != 1
            or diagnostics.get("parser")
            or diagnostics.get("link")
            or validation_errors
        ):
            raise OracleError("runner returned a logically inconsistent ok result")
    elif ir_value is not None or not isinstance(failure, dict):
        raise OracleError("runner returned a logically inconsistent invalid result")
    return result


def _workspace_payload(workspace_sources: Any, filename: str) -> list[dict[str, str]]:
    if workspace_sources is None:
        return []
    if not isinstance(workspace_sources, dict):
        raise OracleError("workspace_sources must be a filename-to-source object")
    payload: list[dict[str, str]] = []
    for name, source in sorted(workspace_sources.items()):
        candidate = Path(name) if isinstance(name, str) else Path("")
        if (
            not isinstance(name, str)
            or not name
            or candidate.is_absolute()
            or ".." in candidate.parts
            or not name.endswith(".metis")
            or name == filename
            or not isinstance(source, str)
            or not source
        ):
            raise OracleError("workspace source paths and contents must be safe and non-empty")
        payload.append({"filename": name, "source": source})
    if len(payload) > 512:
        raise OracleError("workspace_sources exceeds the 512-document cap")
    return payload


def verify_oracle_envelope(envelope: Any, *, request: Any | None = None) -> dict[str, Any]:
    """Verify a materialized oracle envelope without executing the compiler."""

    if not isinstance(envelope, dict):
        raise OracleError("oracle envelope must be an object")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(envelope), key=lambda item: list(item.path)
    )
    if errors:
        raise OracleError(f"oracle envelope violates its schema: {errors[0].message}")
    evidence = envelope["evidence"]
    unsigned = json.loads(_canonical(envelope))
    stored_envelope_sha256 = unsigned["evidence"].pop("envelope_sha256")
    if stored_envelope_sha256 != _sha(unsigned):
        raise OracleError("oracle envelope hash does not match its contents")
    expected_runtime = _runtime_identity_policy(
        evidence["toolchain_revision"], evidence["toolchain_tree"]
    )
    if evidence["runtime_identity"] != expected_runtime:
        raise OracleError("oracle runtime identity does not match the immutable runtime policy")
    result = _check_response(
        envelope["result"],
        evidence["toolchain_revision"],
        evidence["toolchain_tree"],
        expected_runtime=expected_runtime,
    )
    if evidence["diagnostics_sha256"] != _sha(result["diagnostics"]):
        raise OracleError("oracle diagnostics hash does not match")
    if evidence["ast_sha256"] != _sha(result["ast"]["inventory"]):
        raise OracleError("oracle AST hash does not match")
    expected_ir = None if result["ir"]["value"] is None else _sha(result["ir"]["value"])
    if evidence["ir_sha256"] != expected_ir:
        raise OracleError("oracle IR hash does not match")
    if evidence["runtime_sha256"] != _sha(evidence["runtime_identity"]):
        raise OracleError("oracle runtime hash does not match")
    if result["runtime"] != evidence["runtime_identity"]:
        raise OracleError("oracle result runtime is not bound to runtime_identity")
    if evidence["metis_status_sha256"] != _sha(evidence["metis_status"]):
        raise OracleError("oracle Metis status hash does not match")
    expected_pins = {
        "runner_sha256": "sha256:" + PINNED_RUNNER_SHA256,
        "tooling_package_sha256": "sha256:" + PINNED_TOOLING_PACKAGE_SHA256,
        "tooling_lock_sha256": "sha256:" + PINNED_TOOLING_LOCK_SHA256,
        "node_modules_sha256": "sha256:" + PINNED_NODE_MODULES_SHA256,
        "node_binary_sha256": "sha256:" + PINNED_NODE_BINARY_SHA256,
        "sandbox_policy_sha256": "sha256:" + SANDBOX_POLICY_SHA256,
        "toolchain_revision": PINNED_METIS_REVISION,
        "toolchain_tree": PINNED_METIS_TREE,
    }
    if any(evidence.get(field) != value for field, value in expected_pins.items()):
        raise OracleError("oracle evidence does not match the registered toolchain pins")
    if request is not None and evidence["input_sha256"] != _sha(request):
        raise OracleError("oracle input hash does not match the supplied request")
    return envelope


def run_oracle(
    source: str,
    *,
    metis_root: str | os.PathLike[str],
    runner_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    filename: str = "oracle.metis",
    endpoint: str | None = None,
    workspace_sources: dict[str, str] | None = None,
    timeout: float = 60.0,
    expected_revision: str = PINNED_METIS_REVISION,
) -> dict[str, Any]:
    """Execute the self-contained source without writing the Metis checkout."""

    if not isinstance(source, str) or not source:
        raise OracleError("source must be a non-empty string")
    if (
        not isinstance(filename, str)
        or Path(filename).is_absolute()
        or not filename.endswith(".metis")
        or ".." in Path(filename).parts
    ):
        raise OracleError("filename must be a relative .metis name")
    if endpoint is not None and (not isinstance(endpoint, str) or not endpoint):
        raise OracleError("endpoint must be null or a non-empty string")
    if output_path is not None and output_dir is not None:
        raise OracleError("provide output_path or output_dir, not both")
    if output_path is None and output_dir is None:
        raise OracleError("an output path is required")

    _assert_sandbox_policy()
    root, revision, tree, toolchain_runtime = validate_pinned_metis(
        metis_root, expected_revision=expected_revision
    )
    runner = _validate_runner_path(runner_path, root)
    if output_path is None:
        directory = _resolve_absolute(output_dir or "", "output_dir")
        if _contains(root, directory):
            raise OracleError("output_dir may not be inside the Metis checkout")
        output_path = directory / "oracle-result.json"
    output = _validate_output_path(output_path, root)
    output.parent.mkdir(parents=True, exist_ok=True)

    node, node_binary_sha256 = _resolve_pinned_node()
    runtime = _runtime_identity(
        PINNED_NODE_VERSION, node_binary_sha256, revision, tree, toolchain_runtime
    )
    request = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "filename": filename,
        "endpoint": endpoint,
        # The physical snapshot is intentionally omitted from the evidence so
        # repeated runs remain byte deterministic.
        "metis_root": f"snapshot://{revision}/{tree}",
        "metis_revision": revision,
        "metis_tree": tree,
        "workspace_sources": _workspace_payload(workspace_sources, filename),
    }
    request_bytes = _canonical(request)
    before_status = _git(root, "status", "--porcelain=v1", "--untracked-files=no")
    before_revision = _git(root, "rev-parse", "HEAD")
    before_tree = _git(root, "rev-parse", "HEAD^{tree}")
    if before_revision != revision or before_tree != tree:
        raise OracleError("Metis checkout changed during validation")
    source_modules = root / "tooling" / "node_modules"
    source_modules_before = _node_modules_sha256(source_modules)
    holder, snapshot, snapshot_modules, snapshot_runner, snapshot_node = _build_isolated_snapshot(
        root, revision, tree, toolchain_runtime, runner, node
    )
    try:
        snapshot_modules_before = _node_modules_sha256(snapshot_modules)
        snapshot_modules_pin = toolchain_runtime["node_modules_sha256"]
        if snapshot_modules_before != snapshot_modules_pin:
            raise OracleError("isolated tooling node_modules changed before execution")
        if _file_sha256(snapshot_runner) != PINNED_RUNNER_SHA256:
            raise OracleError("isolated runner changed before execution")
        if _file_sha256(snapshot_node) != PINNED_NODE_BINARY_SHA256:
            raise OracleError("isolated Node binary changed before execution")
        snapshot_identity = f"snapshot://{revision}/{tree}"
        command = [
            str(snapshot_node),
            "--import",
            str(snapshot / "tooling" / "node_modules" / "tsx" / "dist" / "loader.mjs"),
            str(snapshot_runner),
            "--metis-root",
            str(snapshot),
            "--metis-revision",
            revision,
            "--metis-tree",
            tree,
            "--tsx-path",
            str(snapshot / "tooling" / "node_modules" / "tsx" / "dist" / "loader.mjs"),
            "--runtime-node-path",
            runtime["node_path"],
            "--node-actual-path",
            str(snapshot_node.resolve()),
            "--runtime-tsx-path",
            runtime["tsx_path"],
            "--runtime-runner-path",
            runtime["runner_path"],
            "--runner-actual-path",
            str(snapshot_runner),
            "--snapshot-identity",
            snapshot_identity,
            "--node-modules-sha256",
            snapshot_modules_pin,
            "--runner-sha256",
            PINNED_RUNNER_SHA256,
            "--node-binary-sha256",
            PINNED_NODE_BINARY_SHA256,
            "--sandbox-policy-version",
            SANDBOX_POLICY_VERSION,
            "--sandbox-policy-sha256",
            SANDBOX_POLICY_SHA256,
            "--tooling-package-sha256",
            toolchain_runtime["package_sha256"],
            "--tooling-lock-sha256",
            toolchain_runtime["lock_sha256"],
        ]
        sandbox_command = [str(SANDBOX_EXEC_PATH), "-p", SANDBOX_POLICY, *command]
        completed: subprocess.CompletedProcess[str] | None = None
        launch_error: Exception | None = None
        try:
            completed = subprocess.run(
                sandbox_command,
                cwd=snapshot / "tooling",
                input=request_bytes.decode("utf-8"),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=STERILE_ENV,
            )
        except (OSError, subprocess.SubprocessError) as error:
            launch_error = error
        snapshot_modules_after = _node_modules_sha256(snapshot_modules)
        if snapshot_modules_after != snapshot_modules_before:
            raise OracleError("oracle runner changed isolated tooling node_modules")
        if _file_sha256(snapshot_runner) != PINNED_RUNNER_SHA256:
            raise OracleError("oracle runner changed isolated runner")
        if _file_sha256(snapshot_node) != PINNED_NODE_BINARY_SHA256:
            raise OracleError("oracle runner changed isolated Node binary")
        after_status = _git(root, "status", "--porcelain=v1", "--untracked-files=no")
        after_revision = _git(root, "rev-parse", "HEAD")
        after_tree = _git(root, "rev-parse", "HEAD^{tree}")
        source_modules_after = _node_modules_sha256(source_modules)
        if (
            after_status != before_status
            or after_revision != before_revision
            or after_tree != before_tree
            or source_modules_after != source_modules_before
        ):
            raise OracleError("oracle runner changed the read-only Metis checkout")
        if launch_error is not None:
            raise OracleError(f"oracle runner failed to start: {launch_error}") from launch_error
        if completed is None:
            raise OracleError("oracle runner produced no process result")
        if completed.returncode != 0:
            raise OracleError(
                f"oracle runner exited {completed.returncode}: {completed.stderr.strip()[:500]}"
            )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise OracleError("oracle runner emitted malformed JSON") from error
        if completed.stdout.strip() != _canonical(result).decode("utf-8"):
            raise OracleError("oracle runner output is not canonical JSON")
        result = _check_response(result, revision, tree, expected_runtime=runtime)
        evidence = {
            "input_sha256": _sha(request),
            "diagnostics_sha256": _sha(result["diagnostics"]),
            "ast_sha256": _sha(result["ast"]["inventory"]),
            "ir_sha256": None if result["ir"]["value"] is None else _sha(result["ir"]["value"]),
            "toolchain_revision": revision,
            "toolchain_tree": tree,
            "runtime_sha256": _sha(runtime),
            "runtime_identity": runtime,
            "runner_sha256": "sha256:" + PINNED_RUNNER_SHA256,
            "tooling_package_sha256": "sha256:" + toolchain_runtime["package_sha256"],
            "tooling_lock_sha256": "sha256:" + toolchain_runtime["lock_sha256"],
            "node_modules_sha256": "sha256:" + toolchain_runtime["node_modules_sha256"],
            "node_binary_sha256": "sha256:" + PINNED_NODE_BINARY_SHA256,
            "sandbox_policy_sha256": "sha256:" + SANDBOX_POLICY_SHA256,
            "metis_status_sha256": _sha(before_status),
            "metis_status": before_status,
        }
        envelope: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "result": result,
            "evidence": evidence,
        }
        envelope["evidence"]["envelope_sha256"] = _sha(envelope)
        verify_oracle_envelope(envelope, request=request)
        payload = _canonical(envelope)
        with tempfile.NamedTemporaryFile(
            "wb", dir=output.parent, prefix=f".{output.name}.", delete=False
        ) as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
            temporary = Path(tmp.name)
        try:
            os.replace(temporary, output)
            directory_fd = os.open(output.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
        return envelope
    finally:
        holder.cleanup()


run_metis_oracle = run_oracle
execute_oracle = run_oracle
