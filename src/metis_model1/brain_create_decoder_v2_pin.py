"""Fail-closed successor pin for the dynamic Model 1 CREATE-v2 decoder.

The pinned v1 decoder remains immutable.  This module certifies the distinct
wire-v6 path: a static body schema is narrowed by a closed, handle-only
constraint derived by the host.  It is a runtime-integrity check only; it
does not invoke a model, read a tenant, render source, or establish quality.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import Any

from metis_model1.brain_create_decoder_pin import (
    MAX_BOUND_FILE_BYTES,
    MAX_MANIFEST_BYTES,
    _canonical,
    _decode_object,
    _read_regular,
    _safe_relative,
    _sha256,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_RELATIVE = PurePosixPath("manifests/metis-brain-model1-create-decoder-v2.json")
MANIFEST_PATH = PROJECT_ROOT / MANIFEST_RELATIVE

# This is replaced after the manifest is materialized.  The file identity is
# independent from the semantic manifest digest returned by ``manifest_sha256``.
MANIFEST_FILE_SHA256 = "sha256:409f53e1faaf73470d1f4bc5c5c7ad7b7a31707067e636ecb2459b0ccfd387b1"

_SHA256_LENGTH = len("sha256:") + 64
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
    "no_source_authority",
    "no_private_authority_exposure",
)
_EXPECTED_TOP_LEVEL = {
    "schema_version",
    "pin_id",
    "status",
    "role",
    "wire",
    "runtime",
    "authoritative_schema",
    "decoder_projection",
    "decoder_constraint",
    "bound_decoder_schema",
    "create_prefix",
    "worker",
    "decoder_cache",
    "host_guards",
    "policy",
    "nonclaims",
}


class BrainCreateDecoderV2PinError(ValueError):
    """The dynamic CREATE-v2 decoder contract failed closed."""


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """Return the canonical semantic identity for the v2 manifest."""

    return _sha256(_canonical(manifest))


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _exact_mapping(value: Any, keys: set[str], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise BrainCreateDecoderV2PinError(f"{label} field roster drifted")
    return value


def _strict_file_identity(value: Any, *, label: str, path: str) -> Mapping[str, Any]:
    item = _exact_mapping(value, {"path", "sha256"}, label=label)
    if item["path"] != path or not _is_sha256(item["sha256"]):
        raise BrainCreateDecoderV2PinError(f"{label} identity drifted")
    return item


def _strict_implementation(
    value: Any, *, label: str, implementation: str, keys: set[str]
) -> Mapping[str, Any]:
    item = _exact_mapping(value, keys, label=label)
    if item.get("implementation") != implementation:
        raise BrainCreateDecoderV2PinError(f"{label} implementation drifted")
    return item


def _validate_constraint_payload(value: Any) -> Mapping[str, Any]:
    item = _exact_mapping(value, {"v", "p", "a", "d", "x"}, label="constraint payload")
    if (
        item["v"] != 1
        or not _is_sha256(item["p"])
        or not isinstance(item["a"], list)
        or not item["a"]
        or item["a"] != sorted(item["a"])
        or len(item["a"]) != len(set(item["a"]))
        or any(type(handle) is not int or not 0 <= handle <= 63 for handle in item["a"])
        or not isinstance(item["d"], list)
        or not isinstance(item["x"], list)
        or not item["d"]
        and not item["x"]
    ):
        raise BrainCreateDecoderV2PinError("constraint payload identity drifted")
    active = frozenset(item["a"])
    for operation in item["d"]:
        if not isinstance(operation, Mapping):
            raise BrainCreateDecoderV2PinError("constraint direct operation is invalid")
        expected = {
            "a": {"k", "q", "s", "n"},
            "s": {"k", "q", "s", "v"},
            "d": {"k", "q", "n"},
        }.get(operation.get("k"))
        requirements = operation.get("q")
        if (
            expected is None
            or set(operation) != expected
            or not isinstance(requirements, list)
            or not 1 <= len(requirements) <= 4
            or requirements != sorted(requirements)
            or len(requirements) != len(set(requirements))
            or any(type(handle) is not int or handle not in active for handle in requirements)
            or any(
                type(operation[key]) is not int or not 0 <= operation[key] <= 255
                for key in expected - {"k", "q"}
            )
        ):
            raise BrainCreateDecoderV2PinError("constraint direct operation drifted")
    if item["d"] != sorted(item["d"], key=_canonical):
        raise BrainCreateDecoderV2PinError("constraint direct operation order drifted")
    for descriptor in item["x"]:
        if not isinstance(descriptor, Mapping) or set(descriptor) != {"s", "r", "w"}:
            raise BrainCreateDecoderV2PinError("constraint expansion descriptor is invalid")
        rows = descriptor["w"]
        if (
            type(descriptor["s"]) is not int
            or type(descriptor["r"]) is not int
            or not 0 <= descriptor["s"] <= 255
            or not 0 <= descriptor["r"] <= 255
            or not isinstance(rows, list)
            or not 1 <= len(rows) <= 12
            or rows != sorted(rows)
            or len(rows) != len(set(rows))
            or any(type(handle) is not int or not 0 <= handle <= 255 for handle in rows)
        ):
            raise BrainCreateDecoderV2PinError("constraint expansion descriptor drifted")
    if item["x"] != sorted(item["x"], key=_canonical):
        raise BrainCreateDecoderV2PinError("constraint expansion descriptor order drifted")
    return item


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    _exact_mapping(manifest, _EXPECTED_TOP_LEVEL, label="decoder v2 pin")
    if (
        type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 1
        or manifest["pin_id"] != "metis-brain-model1-create-decoder/2026-09-05-v2"
        or manifest["status"] != "runtime_contract_ready"
        or manifest["role"] != "metis_brain_model1_create_delta_planner_v2"
    ):
        raise BrainCreateDecoderV2PinError("decoder v2 pin identity drifted")

    wire = _exact_mapping(manifest["wire"], {"schema_version", "operation"}, label="wire")
    if type(wire["schema_version"]) is not int or wire != {
        "schema_version": 6,
        "operation": "plan_create_v2",
    }:
        raise BrainCreateDecoderV2PinError("decoder v2 wire identity drifted")

    runtime = _exact_mapping(
        manifest["runtime"],
        {"python", "qualification_lock", "packages", "decoder", "network"},
        label="runtime",
    )
    lock = _strict_file_identity(
        runtime["qualification_lock"], label="qualification lock", path="qualification/uv.lock"
    )
    packages = _exact_mapping(runtime["packages"], set(_EXPECTED_PACKAGES), label="packages")
    if (
        runtime["python"] != "3.12.10"
        or runtime["decoder"] != "llguidance-1.8.0"
        or runtime["network"] != "denied"
        or dict(packages) != _EXPECTED_PACKAGES
        or not _is_sha256(lock["sha256"])
    ):
        raise BrainCreateDecoderV2PinError("decoder v2 runtime identity drifted")

    schema = _strict_file_identity(
        manifest["authoritative_schema"],
        label="authoritative body schema",
        path="schemas/metis-brain-create-delta-plan-body-v2.schema.json",
    )
    projection = _strict_implementation(
        manifest["decoder_projection"],
        label="static decoder projection",
        implementation="metis_model1.initial_local_qlora_runtime._create_plan_v2_decoder_schema",
        keys={"implementation", "canonical_sha256"},
    )
    if not _is_sha256(schema["sha256"]) or not _is_sha256(projection["canonical_sha256"]):
        raise BrainCreateDecoderV2PinError("decoder v2 schema identity drifted")

    constraint = _strict_implementation(
        manifest["decoder_constraint"],
        label="closed decoder constraint",
        implementation="metis_model1.brain_create_plan_v2.derive_create_plan_v2_decoder_constraint",
        keys={"implementation", "payload", "canonical_sha256"},
    )
    _validate_constraint_payload(constraint["payload"])
    if not _is_sha256(constraint["canonical_sha256"]) or constraint["canonical_sha256"] != _sha256(
        _canonical(constraint["payload"])
    ):
        raise BrainCreateDecoderV2PinError("closed decoder constraint digest drifted")

    bound = _strict_implementation(
        manifest["bound_decoder_schema"],
        label="bound decoder schema",
        implementation="metis_model1.initial_local_qlora_runtime._create_plan_v2_bound_decoder_schema",
        keys={"implementation", "sample_constraint_sha256", "canonical_sha256"},
    )
    if bound["sample_constraint_sha256"] != constraint["canonical_sha256"] or not _is_sha256(
        bound["canonical_sha256"]
    ):
        raise BrainCreateDecoderV2PinError("bound decoder schema identity drifted")

    prefix = _strict_implementation(
        manifest["create_prefix"],
        label="CREATE v2 prefix",
        implementation="metis_model1.brain_mlx_runtime._create_plan_v2_prefix_messages",
        keys={"implementation", "canonical_sha256", "message_count"},
    )
    if (
        not _is_sha256(prefix["canonical_sha256"])
        or type(prefix["message_count"]) is not int
        or prefix["message_count"] != 2
    ):
        raise BrainCreateDecoderV2PinError("CREATE v2 prefix identity drifted")

    _strict_file_identity(
        manifest["worker"],
        label="CREATE v2 worker",
        path="src/metis_model1/initial_local_qlora_runtime.py",
    )
    cache = _strict_implementation(
        manifest["decoder_cache"],
        label="decoder cache",
        implementation="metis_model1.initial_local_qlora_runtime.MAX_CREATE_PLAN_V2_DECODER_CACHE",
        keys={"implementation", "maximum_entries"},
    )
    if type(cache["maximum_entries"]) is not int or cache["maximum_entries"] != 32:
        raise BrainCreateDecoderV2PinError("decoder cache cap drifted")

    guards = _strict_implementation(
        manifest["host_guards"],
        label="host guards",
        implementation="metis_model1.brain_typed_create_pipeline.run_typed_create_pipeline_v2",
        keys={"implementation", "path", "sha256", "membership", "admission", "permit"},
    )
    if (
        guards["path"] != "src/metis_model1/brain_typed_create_pipeline.py"
        or not _is_sha256(guards["sha256"])
        or guards["membership"]
        != "metis_model1.brain_create_plan_v2.validate_create_plan_v2_decoder_constraint_membership"
        or guards["admission"] != "metis_model1.brain_create_plan_v2.admit_create_delta_plan_v2"
        or guards["permit"] != "metis_model1.brain_create_plan_v2.issue_create_delta_plan_v2_permit"
    ):
        raise BrainCreateDecoderV2PinError("host guard identity drifted")

    policy = _exact_mapping(
        manifest["policy"],
        {
            "authoritative_host_membership_required",
            "authoritative_host_admission_required",
            "delta_permit_required",
            "source_generation_forbidden",
            "private_authority_forbidden",
            "network_denied",
        },
        label="policy",
    )
    if any(type(value) is not bool or value is not True for value in policy.values()):
        raise BrainCreateDecoderV2PinError("decoder v2 policy drifted")
    nonclaims = manifest["nonclaims"]
    if (
        not isinstance(nonclaims, Sequence)
        or isinstance(nonclaims, str | bytes | bytearray)
        or tuple(nonclaims) != _EXPECTED_NONCLAIMS
    ):
        raise BrainCreateDecoderV2PinError("decoder v2 nonclaim roster drifted")


def load_brain_create_decoder_v2_pin(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Load the v2 manifest through a bounded no-symlink read."""

    try:
        raw = _read_regular(
            Path(root), MANIFEST_RELATIVE, maximum=MAX_MANIFEST_BYTES, label="decoder v2 manifest"
        )
    except ValueError as error:
        raise BrainCreateDecoderV2PinError(str(error)) from error
    if _sha256(raw) != MANIFEST_FILE_SHA256:
        raise BrainCreateDecoderV2PinError("decoder v2 manifest differs from its fixed digest")
    try:
        manifest = _decode_object(raw, label="decoder v2 manifest")
        _validate_manifest(manifest)
    except ValueError as error:
        raise BrainCreateDecoderV2PinError(str(error)) from error
    return manifest


def _live_runtime_identity(package_names: Sequence[str]) -> tuple[str, dict[str, str]]:
    try:
        packages = {name: version(name) for name in package_names}
    except PackageNotFoundError as error:
        raise BrainCreateDecoderV2PinError("decoder v2 runtime package is unavailable") from error
    return ".".join(str(part) for part in sys.version_info[:3]), packages


def _function_call_names(
    raw: bytes, *, relative: PurePosixPath, function_name: str
) -> frozenset[str]:
    """Return direct call names from exactly one statically pinned function."""

    try:
        tree = ast.parse(raw.decode("utf-8"), filename=str(relative))
    except (UnicodeError, SyntaxError, RecursionError) as error:
        raise BrainCreateDecoderV2PinError(f"{function_name} source is invalid") from error
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    if len(functions) != 1:
        raise BrainCreateDecoderV2PinError(
            f"{function_name} implementation is missing or duplicated"
        )
    names: set[str] = set()
    for node in ast.walk(functions[0]):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return frozenset(names)


def _prefix_ast_value(node: ast.AST, bindings: Mapping[str, Any]) -> Any:
    """Evaluate only the literal expression grammar used by the pinned v2 prefix."""

    if isinstance(node, ast.Constant):
        if type(node.value) not in {str, int, float, bool, type(None)}:
            raise BrainCreateDecoderV2PinError("CREATE v2 prefix contains an unsupported literal")
        return node.value
    if isinstance(node, ast.Name):
        try:
            return bindings[node.id]
        except KeyError as error:
            raise BrainCreateDecoderV2PinError(
                "CREATE v2 prefix contains an unpinned name"
            ) from error
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        owner = bindings.get(node.value.id)
        if not isinstance(owner, Mapping) or node.attr not in owner:
            raise BrainCreateDecoderV2PinError("CREATE v2 prefix contains an unpinned attribute")
        return owner[node.attr]
    if isinstance(node, ast.List):
        return [_prefix_ast_value(item, bindings) for item in node.elts]
    if isinstance(node, ast.Dict):
        if len(node.keys) != len(node.values) or any(key is None for key in node.keys):
            raise BrainCreateDecoderV2PinError("CREATE v2 prefix dictionary is invalid")
        return {
            _prefix_ast_value(key, bindings): _prefix_ast_value(value, bindings)
            for key, value in zip(node.keys, node.values, strict=True)
        }
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _prefix_ast_value(node.left, bindings)
        right = _prefix_ast_value(node.right, bindings)
        if not isinstance(left, str) or not isinstance(right, str):
            raise BrainCreateDecoderV2PinError("CREATE v2 prefix concatenation is not text")
        return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue) and value.conversion == -1:
                if value.format_spec is not None:
                    raise BrainCreateDecoderV2PinError("CREATE v2 prefix format specifier drifted")
                parts.append(str(_prefix_ast_value(value.value, bindings)))
            else:
                raise BrainCreateDecoderV2PinError("CREATE v2 prefix interpolation drifted")
        return "".join(parts)
    raise BrainCreateDecoderV2PinError("CREATE v2 prefix expression drifted")


def _prefix_from_source(
    root: Path, *, body_schema_sha256: str, projection_sha256: str
) -> tuple[int, list[dict[str, str]]]:
    relative = PurePosixPath("src/metis_model1/brain_mlx_runtime.py")
    try:
        raw = _read_regular(
            root, relative, maximum=MAX_BOUND_FILE_BYTES, label="CREATE v2 prefix source"
        )
    except ValueError as error:
        raise BrainCreateDecoderV2PinError(str(error)) from error
    try:
        tree = ast.parse(raw.decode("utf-8"), filename=str(relative))
    except (UnicodeError, SyntaxError, RecursionError) as error:
        raise BrainCreateDecoderV2PinError("CREATE v2 prefix source is invalid") from error
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_create_plan_v2_prefix_messages"
    ]
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "CREATE_PLAN_V2_WIRE_VERSION"
            for target in node.targets
        )
    ]
    if len(functions) != 1 or len(assignments) != 1:
        raise BrainCreateDecoderV2PinError(
            "CREATE v2 prefix implementation is missing or duplicated"
        )
    try:
        wire = ast.literal_eval(assignments[0].value)
    except (TypeError, ValueError, SyntaxError) as error:
        raise BrainCreateDecoderV2PinError(
            "CREATE v2 wire implementation is not literal"
        ) from error
    body = functions[0].body
    if (
        type(wire) is not int
        or len(body) != 2
        or not isinstance(body[0], ast.Expr)
        or not isinstance(body[0].value, ast.Constant)
        or not isinstance(body[0].value.value, str)
        or not isinstance(body[1], ast.Return)
        or body[1].value is None
    ):
        raise BrainCreateDecoderV2PinError("CREATE v2 prefix implementation shape drifted")
    prefix = _prefix_ast_value(
        body[1].value,
        {
            "CREATE_DELTA_PLAN_BODY_V2_SCHEMA_SHA256": body_schema_sha256,
            "qualified_runtime": {"CREATE_PLAN_V2_DECODER_SCHEMA_SHA256": projection_sha256},
        },
    )
    if not isinstance(prefix, list) or any(
        not isinstance(item, dict)
        or set(item) != {"role", "content"}
        or any(not isinstance(value, str) for value in item.values())
        for item in prefix
    ):
        raise BrainCreateDecoderV2PinError("CREATE v2 prefix output shape drifted")
    return wire, prefix


def verify_brain_create_decoder_v2_runtime_subset(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Verify packages only in the interpreter that runs the isolated worker."""

    manifest = load_brain_create_decoder_v2_pin(root)
    runtime = manifest["runtime"]
    live_python, live_packages = _live_runtime_identity(tuple(_EXPECTED_PACKAGES))
    if live_python != runtime["python"] or live_packages != _EXPECTED_PACKAGES:
        raise BrainCreateDecoderV2PinError("live decoder v2 runtime differs")
    return {"status": manifest["status"], "python": live_python, "packages": live_packages}


def verify_brain_create_decoder_v2_pin(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Verify every host-visible v2 binding without inspecting worker packages."""

    root = Path(root)
    manifest = load_brain_create_decoder_v2_pin(root)
    runtime = manifest["runtime"]
    lock = runtime["qualification_lock"]
    try:
        lock_raw = _read_regular(
            root,
            _safe_relative(lock["path"], label="qualification lock path"),
            maximum=MAX_BOUND_FILE_BYTES,
            label="qualification lock",
        )
    except ValueError as error:
        raise BrainCreateDecoderV2PinError(str(error)) from error
    if _sha256(lock_raw) != lock["sha256"]:
        raise BrainCreateDecoderV2PinError("qualification lock differs")

    schema_identity = manifest["authoritative_schema"]
    try:
        schema_raw = _read_regular(
            root,
            _safe_relative(schema_identity["path"], label="body schema path"),
            maximum=MAX_BOUND_FILE_BYTES,
            label="authoritative body schema",
        )
        schema = _decode_object(schema_raw, label="authoritative body schema")
    except ValueError as error:
        raise BrainCreateDecoderV2PinError(str(error)) from error
    if _sha256(_canonical(schema)) != schema_identity["sha256"]:
        raise BrainCreateDecoderV2PinError("authoritative body schema differs")

    worker_identity = manifest["worker"]
    try:
        worker_raw = _read_regular(
            root,
            _safe_relative(worker_identity["path"], label="worker path"),
            maximum=MAX_BOUND_FILE_BYTES,
            label="CREATE v2 worker",
        )
    except ValueError as error:
        raise BrainCreateDecoderV2PinError(str(error)) from error
    if _sha256(worker_raw) != worker_identity["sha256"]:
        raise BrainCreateDecoderV2PinError("CREATE v2 worker differs")

    from metis_model1 import initial_local_qlora_runtime as worker_runtime  # noqa: PLC0415

    if (
        manifest["wire"]["schema_version"] != worker_runtime.CREATE_PLAN_V2_WIRE_VERSION
        or runtime["decoder"] != worker_runtime.CREATE_PLAN_V2_DECODER
        or schema_identity["sha256"] != worker_runtime.CREATE_PLAN_V2_SCHEMA_SHA256
        or manifest["decoder_cache"]["maximum_entries"]
        != worker_runtime.MAX_CREATE_PLAN_V2_DECODER_CACHE
    ):
        raise BrainCreateDecoderV2PinError("CREATE v2 worker constants differ")
    projection = worker_runtime._create_plan_v2_decoder_schema(schema)
    if _sha256(_canonical(projection)) != manifest["decoder_projection"]["canonical_sha256"]:
        raise BrainCreateDecoderV2PinError("CREATE v2 static decoder projection differs")
    constraint_payload = manifest["decoder_constraint"]["payload"]
    constraint = worker_runtime._create_plan_v2_decoder_constraint(constraint_payload)
    if (
        _canonical(constraint) != _canonical(constraint_payload)
        or _sha256(_canonical(constraint)) != manifest["decoder_constraint"]["canonical_sha256"]
    ):
        raise BrainCreateDecoderV2PinError("CREATE v2 closed decoder constraint differs")
    bound = worker_runtime._create_plan_v2_bound_decoder_schema(schema, constraint)
    if _sha256(_canonical(bound)) != manifest["bound_decoder_schema"]["canonical_sha256"]:
        raise BrainCreateDecoderV2PinError("CREATE v2 bound decoder schema differs")

    wire, prefix = _prefix_from_source(
        root,
        body_schema_sha256=schema_identity["sha256"],
        projection_sha256=manifest["decoder_projection"]["canonical_sha256"],
    )
    if (
        wire != manifest["wire"]["schema_version"]
        or len(prefix) != manifest["create_prefix"]["message_count"]
        or _sha256(_canonical(prefix)) != manifest["create_prefix"]["canonical_sha256"]
    ):
        raise BrainCreateDecoderV2PinError("CREATE v2 prefix differs")

    guards = manifest["host_guards"]
    try:
        guard_relative = _safe_relative(guards["path"], label="host guard path")
        guard_raw = _read_regular(
            root, guard_relative, maximum=MAX_BOUND_FILE_BYTES, label="CREATE v2 host guards"
        )
    except ValueError as error:
        raise BrainCreateDecoderV2PinError(str(error)) from error
    if _sha256(guard_raw) != guards["sha256"]:
        raise BrainCreateDecoderV2PinError("CREATE v2 host guards differ")
    calls = _function_call_names(
        guard_raw, relative=guard_relative, function_name="run_typed_create_pipeline_v2"
    )
    required = {
        "validate_create_plan_v2_decoder_constraint_membership",
        "admit_create_delta_plan_v2",
        "issue_create_delta_plan_v2_permit",
    }
    if not required.issubset(calls):
        raise BrainCreateDecoderV2PinError("CREATE v2 host guard call chain differs")

    return {
        "status": manifest["status"],
        "manifest_sha256": manifest_sha256(manifest),
        "wire_schema_version": wire,
        "decoder": runtime["decoder"],
        "body_schema_sha256": schema_identity["sha256"],
        "projection_sha256": manifest["decoder_projection"]["canonical_sha256"],
        "constraint_sha256": manifest["decoder_constraint"]["canonical_sha256"],
        "bound_schema_sha256": manifest["bound_decoder_schema"]["canonical_sha256"],
        "prefix_sha256": manifest["create_prefix"]["canonical_sha256"],
        "worker_sha256": worker_identity["sha256"],
        "decoder_cache_entries": manifest["decoder_cache"]["maximum_entries"],
        "package_count": len(_EXPECTED_PACKAGES),
    }


__all__ = [
    "BrainCreateDecoderV2PinError",
    "MANIFEST_FILE_SHA256",
    "MANIFEST_PATH",
    "PROJECT_ROOT",
    "load_brain_create_decoder_v2_pin",
    "manifest_sha256",
    "verify_brain_create_decoder_v2_pin",
    "verify_brain_create_decoder_v2_runtime_subset",
]
