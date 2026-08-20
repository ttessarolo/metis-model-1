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
import shutil
import subprocess
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
PINNED_RUNNER_SHA256 = "524faa22f6725e660f1d3d36c41d431502a4dcf24adc8109ec04719049a253c4"
LANGUAGE_VERSION = "0.43"
SCHEMA_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = (PROJECT_ROOT / "artifacts").resolve()
RUNNER_PATH = (PROJECT_ROOT / "runtime/metis_oracle/runner.ts").resolve()
SCHEMA_PATH = PROJECT_ROOT / "schemas/oracle-result.schema.json"
_NODE_MODULES_CACHE: dict[Path, str] = {}


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


def _node_modules_sha256(root: Path) -> str:
    cached = _NODE_MODULES_CACHE.get(root)
    if cached is not None:
        return cached
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
    _NODE_MODULES_CACHE[root] = value
    return value


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


def _runtime_identity(node: str, tsx: Path) -> dict[str, str]:
    try:
        node_version = subprocess.run(
            [node, "--version"], check=True, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise OracleError(f"cannot inspect node runtime: {error}") from error
    if node_version != PINNED_NODE_VERSION:
        raise OracleError(
            f"node runtime mismatch: expected {PINNED_NODE_VERSION}, got {node_version}"
        )
    return {
        "node": node_version,
        "node_path": str(Path(node).resolve()),
        "tsx_path": str(tsx.resolve()),
        "runner_path": str(RUNNER_PATH),
    }


def _check_response(result: Any, revision: str, tree: str) -> dict[str, Any]:
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
    if (
        not isinstance(result_runtime, dict)
        or result_runtime.get("node") != PINNED_NODE_VERSION
        or Path(result_runtime.get("runner_path", "")).resolve() != RUNNER_PATH
    ):
        raise OracleError("runner runtime identity does not match the pin")
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
    result = _check_response(
        envelope["result"],
        evidence["toolchain_revision"],
        evidence["toolchain_tree"],
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
    if evidence["metis_status_sha256"] != _sha(evidence["metis_status"]):
        raise OracleError("oracle Metis status hash does not match")
    expected_pins = {
        "runner_sha256": "sha256:" + PINNED_RUNNER_SHA256,
        "tooling_package_sha256": "sha256:" + PINNED_TOOLING_PACKAGE_SHA256,
        "tooling_lock_sha256": "sha256:" + PINNED_TOOLING_LOCK_SHA256,
        "node_modules_sha256": "sha256:" + PINNED_NODE_MODULES_SHA256,
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

    node = shutil.which("node")
    if node is None:
        raise OracleError("node was not found on PATH")
    tsx = root / "tooling" / "node_modules" / ".bin" / "tsx"
    runtime = _runtime_identity(node, tsx)
    request = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "filename": filename,
        "endpoint": endpoint,
        "metis_root": str(root),
        "workspace_sources": _workspace_payload(workspace_sources, filename),
    }
    request_bytes = _canonical(request)
    command = [node, str(tsx), str(runner), "--metis-root", str(root)]
    before_status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    completed: subprocess.CompletedProcess[str] | None = None
    launch_error: Exception | None = None
    try:
        completed = subprocess.run(
            command,
            cwd=root / "tooling",
            input=request_bytes.decode("utf-8"),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        launch_error = error
    after_status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if after_status != before_status:
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
    result = _check_response(result, revision, tree)
    evidence = {
        "input_sha256": _sha(request),
        "diagnostics_sha256": _sha(result["diagnostics"]),
        "ast_sha256": _sha(result["ast"]["inventory"]),
        "ir_sha256": None if result["ir"]["value"] is None else _sha(result["ir"]["value"]),
        "toolchain_revision": revision,
        "toolchain_tree": tree,
        "runtime_sha256": _sha(runtime),
        "runtime_identity": runtime,
        "runner_sha256": "sha256:" + _file_sha256(runner),
        "tooling_package_sha256": "sha256:" + toolchain_runtime["package_sha256"],
        "tooling_lock_sha256": "sha256:" + toolchain_runtime["lock_sha256"],
        "node_modules_sha256": "sha256:" + toolchain_runtime["node_modules_sha256"],
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


run_metis_oracle = run_oracle
execute_oracle = run_oracle
