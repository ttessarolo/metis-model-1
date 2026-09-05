"""Fail-closed runtime-contract pin for Model 1 typed CREATE decoding.

This successor pin is deliberately separate from the immutable training and
qualification freezes.  It proves only that the local runtime components used
to decode a ``CreateDeltaPlan`` still match one exact contract.  It is not an
accuracy, model-quality, distribution, or tenant-authority certificate.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_RELATIVE = PurePosixPath("manifests/metis-brain-model1-create-decoder-v1.json")
MANIFEST_PATH = PROJECT_ROOT / MANIFEST_RELATIVE
PREFIX_SOURCE_RELATIVE = PurePosixPath("src/metis_model1/brain_mlx_runtime.py")
MAX_MANIFEST_BYTES = 64 * 1024
MAX_BOUND_FILE_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 16

# Filled after the manifest has been materialized.  Updating the worker pin
# requires changing the manifest's isolated worker.sha256 and then this digest;
# historical training/runtime freezes remain untouched.
MANIFEST_FILE_SHA256 = "sha256:5baef8d1a53749d7d8aa6e616742b4a287594f9079c24e39aaa0889d67523b3c"

_SHA256_LENGTH = len("sha256:") + 64
_EXPECTED_TOP_LEVEL = {
    "schema_version",
    "pin_id",
    "status",
    "role",
    "wire",
    "runtime",
    "authoritative_schema",
    "decoder_projection",
    "create_prefix",
    "worker",
    "policy",
    "nonclaims",
}
_EXPECTED_PACKAGES = {
    "llguidance": "1.8.0",
    "mlx": "0.32.1",
    "mlx-metal": "0.32.1",
    "mlx-vlm": "0.6.15",
    "numpy": "2.5.2",
    "transformers": "5.14.0",
}
_EXPECTED_NONCLAIMS = (
    "no_accuracy_claim",
    "not_model_qualified",
    "no_model_invocation",
    "no_tenant_authority",
    "no_training_authority",
    "no_distribution_claim",
)


class BrainCreateDecoderPinError(ValueError):
    """The dedicated Model 1 CREATE decoder pin failed closed."""


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
        raise BrainCreateDecoderPinError("decoder pin is not canonical JSON data") from error


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """Return the semantic content identity for the decoder manifest."""

    return _sha256(_canonical(manifest))


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _safe_relative(value: Any, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BrainCreateDecoderPinError(f"{label} is not a relative POSIX path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", "..", ".git"} for part in relative.parts)
    ):
        raise BrainCreateDecoderPinError(f"{label} is not a relative POSIX path")
    return relative


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


def _read_regular(root: Path, relative: PurePosixPath, *, maximum: int, label: str) -> bytes:
    """Read one bounded single-link file through a no-symlink descriptor walk."""

    if type(maximum) is not int or maximum <= 0:
        raise BrainCreateDecoderPinError(f"{label} bound is invalid")
    descriptors: list[int] = []
    file_descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
        directory = os.open(root, directory_flags)
        descriptors.append(directory)
        if not stat.S_ISDIR(os.fstat(directory).st_mode):
            raise BrainCreateDecoderPinError("decoder pin root is not a directory")
        for part in relative.parts[:-1]:
            directory = os.open(part, directory_flags, dir_fd=directory)
            descriptors.append(directory)
            if not stat.S_ISDIR(os.fstat(directory).st_mode):
                raise BrainCreateDecoderPinError(f"{label} ancestry is not a directory")

        name = relative.parts[-1]
        before = os.stat(name, dir_fd=directory, follow_symlinks=False)
        file_descriptor = os.open(name, flags, dir_fd=directory)
        opened = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size <= 0
            or opened.st_size > maximum
        ):
            raise BrainCreateDecoderPinError(f"{label} is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(file_descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(file_descriptor)
        path_after = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except BrainCreateDecoderPinError:
        raise
    except OSError as error:
        raise BrainCreateDecoderPinError(
            f"{label} is unavailable or traverses a symlink"
        ) from error
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        for descriptor in reversed(descriptors):
            os.close(descriptor)

    if (
        len(raw) != opened.st_size
        or len(raw) > maximum
        or _stat_identity(before) != _stat_identity(opened)
        or _stat_identity(opened) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(path_after)
    ):
        raise BrainCreateDecoderPinError(f"{label} changed while read")
    return raw


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BrainCreateDecoderPinError("decoder pin contains duplicate JSON keys")
        result[key] = value
    return result


def _decode_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                BrainCreateDecoderPinError(f"{label} contains non-finite number: {constant}")
            ),
        )
    except BrainCreateDecoderPinError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise BrainCreateDecoderPinError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise BrainCreateDecoderPinError(f"{label} must be an object")
    _validate_json_tree(value)
    return value


def _validate_json_tree(value: Any, *, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise BrainCreateDecoderPinError("decoder pin nesting exceeds its bound")
    if isinstance(value, str):
        if any(
            ord(character) < 0x20
            or 0x7F <= ord(character) <= 0x9F
            or 0xD800 <= ord(character) <= 0xDFFF
            or 0xFDD0 <= ord(character) <= 0xFDEF
            or ord(character) & 0xFFFF in {0xFFFE, 0xFFFF}
            for character in value
        ):
            raise BrainCreateDecoderPinError("decoder pin contains invalid Unicode")
    elif isinstance(value, Mapping):
        if len(value) > 32:
            raise BrainCreateDecoderPinError("decoder pin object exceeds its bound")
        for key, child in value.items():
            if not isinstance(key, str):
                raise BrainCreateDecoderPinError("decoder pin object key is not text")
            _validate_json_tree(key, depth=depth + 1)
            _validate_json_tree(child, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 32:
            raise BrainCreateDecoderPinError("decoder pin array exceeds its bound")
        for child in value:
            _validate_json_tree(child, depth=depth + 1)


def _exact_mapping(value: Any, keys: set[str], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise BrainCreateDecoderPinError(f"{label} field roster drifted")
    return value


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    _exact_mapping(manifest, _EXPECTED_TOP_LEVEL, label="decoder pin")
    if (
        type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 1
        or manifest["pin_id"] != "metis-brain-model1-create-decoder/2026-09-04-v1"
        or manifest["status"] != "runtime_contract_ready"
        or manifest["role"] != "metis_brain_model1_create_delta_planner"
    ):
        raise BrainCreateDecoderPinError("decoder pin identity drifted")

    wire = _exact_mapping(manifest["wire"], {"schema_version", "operation"}, label="wire")
    if type(wire["schema_version"]) is not int or wire != {
        "schema_version": 4,
        "operation": "plan_create",
    }:
        raise BrainCreateDecoderPinError("decoder wire identity drifted")

    runtime = _exact_mapping(
        manifest["runtime"],
        {"python", "qualification_lock", "packages", "decoder", "network"},
        label="runtime",
    )
    lock = _exact_mapping(runtime["qualification_lock"], {"path", "sha256"}, label="lock")
    packages = _exact_mapping(runtime["packages"], set(_EXPECTED_PACKAGES), label="packages")
    if (
        runtime["python"] != "3.12.10"
        or runtime["decoder"] != "llguidance-1.8.0"
        or runtime["network"] != "denied"
        or dict(packages) != _EXPECTED_PACKAGES
        or lock["path"] != "qualification/uv.lock"
        or not _is_sha256(lock["sha256"])
    ):
        raise BrainCreateDecoderPinError("decoder runtime identity drifted")

    schema = _exact_mapping(
        manifest["authoritative_schema"], {"path", "canonical_sha256"}, label="schema"
    )
    if schema["path"] != "schemas/metis-brain-create-delta-plan.schema.json" or not _is_sha256(
        schema["canonical_sha256"]
    ):
        raise BrainCreateDecoderPinError("authoritative schema identity drifted")

    projection = _exact_mapping(
        manifest["decoder_projection"],
        {"implementation", "canonical_sha256", "operation_types"},
        label="decoder projection",
    )
    if (
        projection["implementation"]
        != "metis_model1.initial_local_qlora_runtime._create_plan_decoder_schema"
        or not _is_sha256(projection["canonical_sha256"])
        or type(projection["operation_types"]) is not int
        or projection["operation_types"] != 19
    ):
        raise BrainCreateDecoderPinError("decoder projection identity drifted")

    prefix = _exact_mapping(
        manifest["create_prefix"],
        {"implementation", "canonical_sha256", "message_count"},
        label="create prefix",
    )
    if (
        prefix["implementation"] != "metis_model1.brain_mlx_runtime._create_plan_prefix_messages"
        or not _is_sha256(prefix["canonical_sha256"])
        or type(prefix["message_count"]) is not int
        or prefix["message_count"] != 2
    ):
        raise BrainCreateDecoderPinError("CREATE prefix identity drifted")

    worker = _exact_mapping(manifest["worker"], {"path", "sha256"}, label="worker")
    if worker["path"] != "src/metis_model1/initial_local_qlora_runtime.py" or not _is_sha256(
        worker["sha256"]
    ):
        raise BrainCreateDecoderPinError("CREATE worker identity drifted")

    policy = _exact_mapping(
        manifest["policy"],
        {
            "authoritative_host_validation_required",
            "request_bound_admission_required",
            "delta_permit_required",
            "source_generation_forbidden",
            "network_denied",
        },
        label="policy",
    )
    if set(policy.values()) != {True} or any(type(value) is not bool for value in policy.values()):
        raise BrainCreateDecoderPinError("decoder policy drifted")
    nonclaims = manifest["nonclaims"]
    if (
        not isinstance(nonclaims, Sequence)
        or isinstance(nonclaims, str | bytes | bytearray)
        or tuple(nonclaims) != _EXPECTED_NONCLAIMS
    ):
        raise BrainCreateDecoderPinError("decoder nonclaim roster drifted")


def load_brain_create_decoder_pin(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Load and validate the exact dedicated decoder manifest."""

    raw = _read_regular(
        Path(root), MANIFEST_RELATIVE, maximum=MAX_MANIFEST_BYTES, label="decoder manifest"
    )
    if _sha256(raw) != MANIFEST_FILE_SHA256:
        raise BrainCreateDecoderPinError("decoder manifest differs from its fixed digest")
    manifest = _decode_object(raw, label="decoder manifest")
    _validate_manifest(manifest)
    return manifest


def _live_runtime_identity(package_names: Sequence[str]) -> tuple[str, dict[str, str]]:
    try:
        packages = {name: version(name) for name in package_names}
    except PackageNotFoundError as error:
        raise BrainCreateDecoderPinError("decoder runtime package is unavailable") from error
    python = ".".join(str(part) for part in sys.version_info[:3])
    return python, packages


def _prefix_ast_value(node: ast.AST, bindings: Mapping[str, Any]) -> Any:
    """Evaluate the deliberately literal CREATE prefix expression.

    The host verifier must not import ``brain_mlx_runtime``: that module is
    only available in the qualified worker environment.  The pinned prefix is
    a list of literal dictionaries plus two pinned digest interpolations, so
    evaluating this small AST subset gives the same value without executing
    arbitrary module code or importing worker-only dependencies.
    """

    if isinstance(node, ast.Constant):
        if type(node.value) not in {str, int, float, bool, type(None)}:
            raise BrainCreateDecoderPinError("CREATE prefix contains an unsupported literal")
        return node.value
    if isinstance(node, ast.Name):
        try:
            return bindings[node.id]
        except KeyError as error:
            raise BrainCreateDecoderPinError("CREATE prefix contains an unpinned name") from error
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        owner = bindings.get(node.value.id)
        if not isinstance(owner, Mapping) or node.attr not in owner:
            raise BrainCreateDecoderPinError("CREATE prefix contains an unpinned attribute")
        return owner[node.attr]
    if isinstance(node, ast.List):
        return [_prefix_ast_value(item, bindings) for item in node.elts]
    if isinstance(node, ast.Dict):
        if len(node.keys) != len(node.values) or any(key is None for key in node.keys):
            raise BrainCreateDecoderPinError("CREATE prefix dictionary is invalid")
        return {
            _prefix_ast_value(key, bindings): _prefix_ast_value(value, bindings)
            for key, value in zip(node.keys, node.values, strict=True)
        }
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _prefix_ast_value(node.left, bindings)
        right = _prefix_ast_value(node.right, bindings)
        if not isinstance(left, str) or not isinstance(right, str):
            raise BrainCreateDecoderPinError("CREATE prefix concatenation is not text")
        return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue) and value.conversion == -1:
                rendered = _prefix_ast_value(value.value, bindings)
                if value.format_spec is not None:
                    raise BrainCreateDecoderPinError("CREATE prefix format specifier drifted")
                parts.append(str(rendered))
            else:
                raise BrainCreateDecoderPinError("CREATE prefix interpolation drifted")
        return "".join(parts)
    raise BrainCreateDecoderPinError("CREATE prefix expression drifted")


def _prefix_from_source(
    root: Path, *, schema_sha256: str, projection_sha256: str
) -> tuple[int, list[dict[str, str]]]:
    raw = _read_regular(
        root,
        PREFIX_SOURCE_RELATIVE,
        maximum=MAX_BOUND_FILE_BYTES,
        label="CREATE prefix source",
    )
    try:
        tree = ast.parse(raw.decode("utf-8"), filename=str(PREFIX_SOURCE_RELATIVE))
    except (UnicodeError, SyntaxError, RecursionError) as error:
        raise BrainCreateDecoderPinError("CREATE prefix source is invalid") from error
    functions = [
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "_create_plan_prefix_messages"
    ]
    if len(functions) != 1:
        raise BrainCreateDecoderPinError("CREATE prefix implementation is missing or duplicated")
    wire_constants = [
        target
        for item in tree.body
        if isinstance(item, ast.Assign)
        for target in item.targets
        if isinstance(target, ast.Name) and target.id == "CREATE_PLAN_WIRE_VERSION"
    ]
    if len(wire_constants) != 1:
        raise BrainCreateDecoderPinError("CREATE wire implementation is missing or duplicated")
    wire_assignments = [
        item
        for item in tree.body
        if isinstance(item, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "CREATE_PLAN_WIRE_VERSION"
            for target in item.targets
        )
    ]
    try:
        wire_version = ast.literal_eval(wire_assignments[0].value)
    except (ValueError, TypeError, SyntaxError) as error:
        raise BrainCreateDecoderPinError("CREATE wire implementation is not literal") from error
    if type(wire_version) is not int:
        raise BrainCreateDecoderPinError("CREATE wire implementation is not an integer")
    body = functions[0].body
    if (
        len(body) != 2
        or not isinstance(body[0], ast.Expr)
        or not isinstance(body[0].value, ast.Constant)
        or not isinstance(body[0].value.value, str)
        or not isinstance(body[1], ast.Return)
        or body[1].value is None
    ):
        raise BrainCreateDecoderPinError("CREATE prefix implementation shape drifted")
    prefix = _prefix_ast_value(
        body[1].value,
        {
            "CREATE_DELTA_PLAN_SCHEMA_SHA256": schema_sha256,
            "qualified_runtime": {"CREATE_PLAN_DECODER_SCHEMA_SHA256": projection_sha256},
        },
    )
    if not isinstance(prefix, list) or any(
        not isinstance(item, dict)
        or set(item) != {"role", "content"}
        or any(not isinstance(value, str) for value in item.values())
        for item in prefix
    ):
        raise BrainCreateDecoderPinError("CREATE prefix output shape drifted")
    return wire_version, prefix


def _current_create_prefix() -> tuple[int, list[dict[str, str]]]:
    manifest = load_brain_create_decoder_pin()
    return _prefix_from_source(
        PROJECT_ROOT,
        schema_sha256=manifest["authoritative_schema"]["canonical_sha256"],
        projection_sha256=manifest["decoder_projection"]["canonical_sha256"],
    )


def verify_brain_create_decoder_runtime_subset(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Verify the pinned package subset in the interpreter that will run the worker."""

    manifest = load_brain_create_decoder_pin(root)
    runtime = manifest["runtime"]
    live_python, live_packages = _live_runtime_identity(tuple(_EXPECTED_PACKAGES))
    if live_python != runtime["python"] or live_packages != _EXPECTED_PACKAGES:
        raise BrainCreateDecoderPinError("live decoder runtime differs")
    return {
        "status": "runtime_contract_ready",
        "python": live_python,
        "packages": live_packages,
    }


def verify_brain_create_decoder_pin(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Verify host-visible files and decoder bindings, without worker packages.

    This is the host contract: it checks the manifest, qualification lock,
    authoritative schema, worker source, decoder projection and CREATE prefix.
    Python/package versions belong exclusively to
    :func:`verify_brain_create_decoder_runtime_subset` and are never imported
    or consulted here.
    """

    root = Path(root)
    manifest = load_brain_create_decoder_pin(root)
    runtime = manifest["runtime"]
    lock = runtime["qualification_lock"]
    lock_raw = _read_regular(
        root,
        _safe_relative(lock["path"], label="qualification lock path"),
        maximum=MAX_BOUND_FILE_BYTES,
        label="qualification lock",
    )
    if _sha256(lock_raw) != lock["sha256"]:
        raise BrainCreateDecoderPinError("qualification lock differs")

    schema_identity = manifest["authoritative_schema"]
    schema_raw = _read_regular(
        root,
        _safe_relative(schema_identity["path"], label="schema path"),
        maximum=MAX_BOUND_FILE_BYTES,
        label="authoritative CREATE schema",
    )
    schema = _decode_object(schema_raw, label="authoritative CREATE schema")
    if _sha256(_canonical(schema)) != schema_identity["canonical_sha256"]:
        raise BrainCreateDecoderPinError("authoritative CREATE schema differs")

    worker_identity = manifest["worker"]
    worker_raw = _read_regular(
        root,
        _safe_relative(worker_identity["path"], label="worker path"),
        maximum=MAX_BOUND_FILE_BYTES,
        label="CREATE worker",
    )
    if _sha256(worker_raw) != worker_identity["sha256"]:
        raise BrainCreateDecoderPinError("CREATE worker differs")

    from metis_model1 import initial_local_qlora_runtime as worker_runtime  # noqa: PLC0415

    if (
        manifest["wire"]["schema_version"] != worker_runtime.CREATE_PLAN_WIRE_VERSION
        or runtime["decoder"] != worker_runtime.CREATE_PLAN_DECODER
        or schema_identity["canonical_sha256"] != worker_runtime.CREATE_PLAN_SCHEMA_SHA256
    ):
        raise BrainCreateDecoderPinError("CREATE worker constants differ")
    projection = worker_runtime._create_plan_decoder_schema(schema)
    if _sha256(_canonical(projection)) != manifest["decoder_projection"]["canonical_sha256"]:
        raise BrainCreateDecoderPinError("CREATE decoder projection differs")

    if root == PROJECT_ROOT:
        wire_version, prefix = _current_create_prefix()
    else:
        wire_version, prefix = _prefix_from_source(
            root,
            schema_sha256=schema_identity["canonical_sha256"],
            projection_sha256=manifest["decoder_projection"]["canonical_sha256"],
        )
    if (
        wire_version != manifest["wire"]["schema_version"]
        or len(prefix) != manifest["create_prefix"]["message_count"]
        or _sha256(_canonical(prefix)) != manifest["create_prefix"]["canonical_sha256"]
    ):
        raise BrainCreateDecoderPinError("CREATE prefix differs")

    return {
        "status": "runtime_contract_ready",
        "manifest_sha256": manifest_sha256(manifest),
        "wire_schema_version": wire_version,
        "decoder": runtime["decoder"],
        "schema_sha256": schema_identity["canonical_sha256"],
        "projection_sha256": manifest["decoder_projection"]["canonical_sha256"],
        "prefix_sha256": manifest["create_prefix"]["canonical_sha256"],
        "worker_sha256": worker_identity["sha256"],
        "package_count": len(_EXPECTED_PACKAGES),
    }


__all__ = [
    "BrainCreateDecoderPinError",
    "MANIFEST_FILE_SHA256",
    "MANIFEST_PATH",
    "PROJECT_ROOT",
    "load_brain_create_decoder_pin",
    "manifest_sha256",
    "verify_brain_create_decoder_pin",
    "verify_brain_create_decoder_runtime_subset",
]
