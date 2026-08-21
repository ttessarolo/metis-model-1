"""Registered, fail-closed Oracle Protocol for W3.

An adapter is not trusted because a caller supplied it. Its canonical identity
must match the module authority registered by the frontier coordinator, and
every result is bound to the exact canonical candidate evaluated.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
import types
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from metis_model1.oracles import (
    NODE_RUNTIME_IDENTITY,
    PINNED_METIS_TREE,
    PINNED_NODE_BINARY_SHA256,
    PINNED_NODE_MODULES_SHA256,
    PINNED_NODE_VERSION,
    PINNED_RUNNER_SHA256,
    PINNED_TOOLING_LOCK_SHA256,
    PINNED_TOOLING_PACKAGE_SHA256,
    SANDBOX_EXEC_IDENTITY,
    SANDBOX_POLICY_SHA256,
    SANDBOX_POLICY_VERSION,
    verify_oracle_envelope,
)
from metis_model1.provenance import canonical_json_bytes

REGISTERED_W3_ORACLE_IDENTITY_SHA256: str | None = None
REGISTERED_W3_ORACLE_ADAPTER: OracleAdapter | None = None
SHA256_PREFIX = "sha256:"
PINNED_METIS_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
LANGUAGE_VERSION = "0.43"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class W3OracleError(ValueError):
    """Raised when the registered Oracle contract is not satisfied exactly."""


class W3OracleTrustError(W3OracleError):
    """Run-fatal authority, identity, evidence or replay failure."""


class W3OracleInfrastructureError(W3OracleError):
    """Run-fatal failure to execute the registered external Oracle."""


class W3CandidateRejected(W3OracleError):
    """Candidate-local semantic failure that may enter the rejected roster."""


class OracleAdapter(Protocol):
    """Independent adapter boundary used by the W3 builder."""

    def identity(self) -> Mapping[str, Any]:
        """Return immutable adapter/toolchain identity material."""

    def evaluate(self, candidate: Mapping[str, Any]) -> Mapping[str, Any]:
        """Evaluate one canonical candidate without network or repository writes."""


def canonical_hash(value: Any) -> str:
    return SHA256_PREFIX + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


PRODUCTION_EXECUTION_PROFILE_JSON = """{
  "receipt_mode": "real-runner-envelopes",
  "roles": {
    "F-1": [{"expected_status": "ok", "role": "author", "source_field": "target_source"}],
    "F-2": [
      {"expected_status": "ok", "role": "before", "source_field": "before_source"},
      {"expected_status": "ok", "role": "after", "source_field": "after_source"}
    ],
    "F-3": [
      {"expected_status": "invalid", "role": "mutated", "source_field": "mutated_source"},
      {"expected_status": "ok", "role": "fixed", "source_field": "fixed_source"}
    ]
  },
  "schema_version": 1
}"""
PRODUCTION_EXECUTION_PROFILE_SHA256 = canonical_hash(json.loads(PRODUCTION_EXECUTION_PROFILE_JSON))


def production_execution_profile() -> dict[str, Any]:
    """Return an isolated canonical copy of the registered phase contract."""

    value = json.loads(PRODUCTION_EXECUTION_PROFILE_JSON)
    if canonical_hash(value) != PRODUCTION_EXECUTION_PROFILE_SHA256:
        raise W3OracleTrustError("production execution profile changed from its pin")
    return value


def valid_hash(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith(SHA256_PREFIX):
        return False
    digest = value[len(SHA256_PREFIX) :]
    if len(digest) != 64 or digest != digest.lower():
        return False
    try:
        int(digest, 16)
    except ValueError:
        return False
    return True


def required_predicates(family: str) -> tuple[str, ...]:
    common = ("parse", "link", "validate", "compile", "semantic")
    if family == "F-1":
        return common
    if family == "F-2":
        return ("patch_minimality", *common)
    if family == "F-3":
        return ("diagnostic", *common)
    raise W3OracleError(f"unsupported W3 family: {family!r}")


@dataclass(frozen=True)
class OracleEvaluation:
    """Fully bound Oracle evidence retained in the W3 run record."""

    envelope: dict[str, Any]
    oracle_result_sha256: str
    semantic_result_sha256: str
    ast_sha256: str
    ir_sha256: str

    @property
    def predicates(self) -> dict[str, bool]:
        return dict(self.envelope["predicates"])

    def dataset_oracles(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "applicable": True,
                "result": "pass",
                "evidence_hash": canonical_hash(
                    {"name": name, "evidence": self.envelope["evidence"][name]}
                ),
            }
            for name in required_predicates(self.envelope["family"])
        ]


def _canonical_copy(value: Any, label: str) -> Any:
    try:
        return json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError) as error:
        raise W3OracleError(f"{label} is not canonical JSON") from error


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return SHA256_PREFIX + digest.hexdigest()


def _code_constant(value: Any) -> Any:
    if isinstance(value, types.CodeType):
        return {"code": _code_material(value)}
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, tuple):
        return {"tuple": [_code_constant(item) for item in value]}
    if isinstance(value, frozenset):
        items = [_code_constant(item) for item in value]
        return {"frozenset": sorted(items, key=canonical_json_bytes)}
    if value is Ellipsis:
        return {"singleton": "Ellipsis"}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise W3OracleError(
        f"Oracle adapter callable contains unsupported constant {type(value).__name__}"
    )


def _code_material(code: types.CodeType) -> dict[str, Any]:
    """Return interpreter-stable code material, excluding adaptive VM caches."""

    return {
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "nlocals": code.co_nlocals,
        "stacksize": code.co_stacksize,
        "flags": code.co_flags,
        "code_bytes": code.co_code.hex(),
        "constants": [_code_constant(item) for item in code.co_consts],
        "names": list(code.co_names),
        "varnames": list(code.co_varnames),
        "filename": code.co_filename,
        "name": code.co_name,
        "qualname": code.co_qualname,
        "firstlineno": code.co_firstlineno,
        "linetable": code.co_linetable.hex(),
        "exceptiontable": code.co_exceptiontable.hex(),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
    }


def stable_code_sha256(code: types.CodeType) -> str:
    """Hash callable code without CPython quickening/marshal instability."""

    if not isinstance(code, types.CodeType):
        raise W3OracleError("Oracle adapter callable has no code object")
    return canonical_hash(_code_material(code))


def _registered_adapter() -> OracleAdapter:
    if REGISTERED_W3_ORACLE_ADAPTER is None:
        raise W3OracleTrustError("W3 Oracle adapter authority is unset")
    return REGISTERED_W3_ORACLE_ADAPTER


def _instance_state(adapter: OracleAdapter) -> dict[str, Any]:
    """Measure the adapter's real instance state without trusting identity claims."""

    try:
        state = vars(adapter)
    except TypeError as error:
        raise W3OracleError("registered Oracle adapter must expose instance vars") from error
    canonical = _canonical_copy(dict(state), "Oracle adapter instance state")
    if not isinstance(canonical, dict):  # defensive: ``vars`` is mapping-shaped
        raise W3OracleError("Oracle adapter instance state must be a JSON object")
    return canonical


def _method_binding(adapter: OracleAdapter, name: str) -> dict[str, str]:
    """Resolve one ordinary class method and reject runtime instance injection."""

    try:
        instance_vars = vars(adapter)
    except TypeError as error:
        raise W3OracleError("registered Oracle adapter must expose instance vars") from error
    if name in instance_vars:
        raise W3OracleError(f"Oracle adapter {name} cannot be overridden on the instance")
    adapter_type = type(adapter)
    try:
        class_callable = inspect.getattr_static(adapter_type, name)
        bound_callable = getattr(adapter, name)
    except AttributeError as error:
        raise W3OracleError(f"Oracle adapter is missing class method {name}") from error
    if (
        not inspect.isfunction(class_callable)
        or not inspect.ismethod(bound_callable)
        or bound_callable.__self__ is not adapter
        or bound_callable.__func__ is not class_callable
    ):
        raise W3OracleError(f"Oracle adapter {name} must be a canonical bound class method")
    try:
        source_file = inspect.getsourcefile(class_callable)
    except TypeError as error:
        raise W3OracleError(f"Oracle adapter {name} has no auditable source file") from error
    if source_file is None:
        raise W3OracleError(f"Oracle adapter {name} has no auditable source file")
    try:
        source_path = Path(source_file).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise W3OracleError(f"Oracle adapter {name} source file is unavailable") from error
    try:
        closure_values = (
            None
            if class_callable.__closure__ is None
            else [cell.cell_contents for cell in class_callable.__closure__]
        )
    except ValueError as error:
        raise W3OracleError(f"Oracle adapter {name} closure contains an empty cell") from error
    defaults = _canonical_copy(
        None if class_callable.__defaults__ is None else list(class_callable.__defaults__),
        f"Oracle adapter {name} defaults",
    )
    kwdefaults = _canonical_copy(class_callable.__kwdefaults__, f"Oracle adapter {name} kwdefaults")
    closure = _canonical_copy(closure_values, f"Oracle adapter {name} closure")
    code_sha256 = stable_code_sha256(class_callable.__code__)
    defaults_sha256 = canonical_hash(defaults)
    kwdefaults_sha256 = canonical_hash(kwdefaults)
    closure_sha256 = canonical_hash(closure)
    callable_sha256 = canonical_hash(
        {
            "code_sha256": code_sha256,
            "defaults_sha256": defaults_sha256,
            "kwdefaults_sha256": kwdefaults_sha256,
            "closure_sha256": closure_sha256,
        }
    )
    return {
        "module": class_callable.__module__,
        "qualname": class_callable.__qualname__,
        "source_file_sha256": _file_hash(source_path),
        "code_sha256": code_sha256,
        "defaults_sha256": defaults_sha256,
        "kwdefaults_sha256": kwdefaults_sha256,
        "closure_sha256": closure_sha256,
        "callable_sha256": callable_sha256,
    }


def _runtime_object_binding(name: str, value: Any) -> dict[str, Any]:
    """Measure one live global used by the production adapter.

    File hashes alone do not bind a Python module after import: a caller can
    replace a module global while leaving every source byte unchanged.  This
    material therefore includes the live callable code/defaults/closure (or an
    exact class/module/value identity) that the adapter will actually resolve.
    """

    if inspect.isfunction(value):
        try:
            source_file = inspect.getsourcefile(value)
        except TypeError as error:
            raise W3OracleTrustError(f"production runtime global {name} has no source") from error
        if source_file is None:
            raise W3OracleTrustError(f"production runtime global {name} has no source")
        try:
            source_path = Path(source_file).resolve(strict=True)
            closure_values = (
                None
                if value.__closure__ is None
                else [cell.cell_contents for cell in value.__closure__]
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise W3OracleTrustError(
                f"production runtime global {name} is not independently measurable"
            ) from error
        defaults = _canonical_copy(
            None if value.__defaults__ is None else list(value.__defaults__),
            f"production runtime global {name} defaults",
        )
        kwdefaults = _canonical_copy(
            value.__kwdefaults__, f"production runtime global {name} kwdefaults"
        )
        closure = _canonical_copy(closure_values, f"production runtime global {name} closure")
        return {
            "kind": "function",
            "module": value.__module__,
            "qualname": value.__qualname__,
            "source_file_sha256": _file_hash(source_path),
            "code_sha256": stable_code_sha256(value.__code__),
            "defaults_sha256": canonical_hash(defaults),
            "kwdefaults_sha256": canonical_hash(kwdefaults),
            "closure_sha256": canonical_hash(closure),
        }
    if inspect.isclass(value):
        try:
            source_file = inspect.getsourcefile(value)
        except TypeError:
            source_file = None
        source_sha256 = None
        if source_file is not None:
            try:
                source_sha256 = _file_hash(Path(source_file).resolve(strict=True))
            except (OSError, RuntimeError) as error:
                raise W3OracleTrustError(
                    f"production runtime class {name} source is unavailable"
                ) from error
        return {
            "kind": "class",
            "module": value.__module__,
            "qualname": value.__qualname__,
            "source_file_sha256": source_sha256,
        }
    if inspect.ismodule(value):
        source_file = getattr(value, "__file__", None)
        source_sha256 = None
        if isinstance(source_file, str):
            try:
                source_sha256 = _file_hash(Path(source_file).resolve(strict=True))
            except (OSError, RuntimeError) as error:
                raise W3OracleTrustError(
                    f"production runtime module {name} source is unavailable"
                ) from error
        return {
            "kind": "module",
            "module": value.__name__,
            "source_file_sha256": source_sha256,
        }
    if isinstance(value, Path):
        return {"kind": "path", "value": str(value)}
    if isinstance(value, bytes):
        return {"kind": "bytes", "value": value.hex()}
    if isinstance(value, (tuple, list)):
        return {
            "kind": type(value).__name__,
            "items": [
                _runtime_object_binding(f"{name}[{index}]", item)
                for index, item in enumerate(value)
            ],
        }
    if isinstance(value, (set, frozenset)):
        items = [_runtime_object_binding(f"{name}[]", item) for item in value]
        return {
            "kind": type(value).__name__,
            "items": sorted(items, key=canonical_json_bytes),
        }
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise W3OracleTrustError(
                f"production runtime global {name} has non-string mapping keys"
            )
        return {
            "kind": "dict",
            "items": {
                key: _runtime_object_binding(f"{name}.{key}", item)
                for key, item in sorted(value.items())
            },
        }
    if value is None or isinstance(value, (bool, int, float, str)):
        return {"kind": "value", "value": value}
    raise W3OracleTrustError(
        f"production runtime global {name} has unsupported type {type(value).__name__}"
    )


def _runtime_function_graph(
    function: types.FunctionType,
    *,
    visiting: set[int],
    memo: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Bind one function to the exact live globals resolved by its bytecode."""

    function_id = id(function)
    binding = _runtime_object_binding(function.__qualname__, function)
    reference = canonical_hash(binding)
    if function_id in visiting:
        return {"cycle": reference}
    if function_id in memo:
        return {"reference": reference, "graph_sha256": canonical_hash(memo[function_id])}
    visiting.add(function_id)
    dependencies: dict[str, Any] = {}
    for name in sorted(set(function.__code__.co_names)):
        if name not in function.__globals__:
            continue
        value = function.__globals__[name]
        if inspect.isfunction(value) and value.__module__.startswith("metis_model1."):
            dependencies[name] = _runtime_function_graph(
                value,
                visiting=visiting,
                memo=memo,
            )
        else:
            dependencies[name] = _runtime_object_binding(name, value)
    visiting.remove(function_id)
    graph = {"binding": binding, "globals": dependencies}
    memo[function_id] = graph
    return graph


def _production_runtime_bindings_sha256(adapter: OracleAdapter) -> str:
    """Hash the live transitive globals resolved by the production adapter."""

    adapter_type = type(adapter)
    if sys.modules.get(adapter_type.__module__) is None:
        raise W3OracleTrustError("production adapter module is not loaded")
    methods: dict[str, Any] = {}
    memo: dict[int, dict[str, Any]] = {}
    for name in ("identity", "evaluate"):
        value = inspect.getattr_static(adapter_type, name, None)
        if not inspect.isfunction(value):
            raise W3OracleTrustError(f"production adapter {name} is not a function")
        methods[name] = _runtime_function_graph(value, visiting=set(), memo=memo)
    serialized = canonical_json_bytes(methods)
    if b'"run_oracle"' not in serialized or b'"verify_oracle_envelope"' not in serialized:
        raise W3OracleTrustError("production adapter runtime dependency closure is incomplete")
    return canonical_hash(methods)


def production_adapter_identity(
    adapter: OracleAdapter,
    *,
    semantic_registry_sha256: str,
    runtime_bindings_sha256: str,
) -> dict[str, Any]:
    """Measure the exact schema-v2 production identity from live files/state."""

    if not valid_hash(semantic_registry_sha256):
        raise W3OracleTrustError("production semantic registry authority is invalid")
    measured_runtime_bindings = _production_runtime_bindings_sha256(adapter)
    if (
        not valid_hash(runtime_bindings_sha256)
        or runtime_bindings_sha256 != measured_runtime_bindings
    ):
        raise W3OracleTrustError(
            "production adapter runtime bindings differ across independent measurements"
        )
    adapter_type = type(adapter)
    source_file = inspect.getsourcefile(adapter_type)
    if source_file is None:
        raise W3OracleTrustError("production adapter class has no auditable source file")
    try:
        source_path = Path(source_file).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise W3OracleTrustError("production adapter source file is unavailable") from error
    bindings = {name: _method_binding(adapter, name) for name in ("identity", "evaluate")}
    method_identity = {
        f"{name}_method_{field}": value
        for name, binding in bindings.items()
        for field, value in binding.items()
    }
    schema_dir = PROJECT_ROOT / "schemas"
    return {
        "schema_version": 2,
        "adapter_id": "metis-model1-w3-production",
        "adapter_version": "1",
        "toolchain_revision": PINNED_METIS_REVISION,
        "toolchain_tree": PINNED_METIS_TREE,
        "language_version": LANGUAGE_VERSION,
        "node": PINNED_NODE_VERSION,
        "node_path": NODE_RUNTIME_IDENTITY,
        "tsx_path": (
            f"snapshot://{PINNED_METIS_REVISION}/{PINNED_METIS_TREE}"
            "/tooling/node_modules/tsx/dist/loader.mjs"
        ),
        "runner_path": (
            f"snapshot://{PINNED_METIS_REVISION}/{PINNED_METIS_TREE}/.metis-oracle/runner.ts"
        ),
        "node_binary_sha256": f"sha256:{PINNED_NODE_BINARY_SHA256}",
        "runner_sha256": f"sha256:{PINNED_RUNNER_SHA256}",
        "tooling_package_sha256": f"sha256:{PINNED_TOOLING_PACKAGE_SHA256}",
        "tooling_lock_sha256": f"sha256:{PINNED_TOOLING_LOCK_SHA256}",
        "node_modules_sha256": f"sha256:{PINNED_NODE_MODULES_SHA256}",
        "sandbox_exec_path": SANDBOX_EXEC_IDENTITY,
        "sandbox_policy_version": SANDBOX_POLICY_VERSION,
        "sandbox_policy_sha256": f"sha256:{SANDBOX_POLICY_SHA256}",
        "class_module": adapter_type.__module__,
        "class_qualname": adapter_type.__qualname__,
        "code_file_sha256": _file_hash(source_path),
        "instance_state_sha256": canonical_hash(_instance_state(adapter)),
        "runtime_bindings_sha256": runtime_bindings_sha256,
        **method_identity,
        "network_access": "disabled",
        "metis_write": "forbidden",
        "receipt_mode": "real-runner-envelopes",
        "semantic_registry_sha256": semantic_registry_sha256,
        "semantic_spec_schema_sha256": _file_hash(schema_dir / "w3-semantic-spec.schema.json"),
        "oracle_protocol_sha256": _file_hash(Path(__file__).resolve()),
        "oracle_bridge_sha256": _file_hash(Path(__file__).with_name("oracles.py")),
        "oracle_result_schema_sha256": _file_hash(schema_dir / "oracle-result.schema.json"),
        "source_register_schema_sha256": _file_hash(schema_dir / "w3-source-register.schema.json"),
        "w3_run_schema_sha256": _file_hash(schema_dir / "w3-run.schema.json"),
        "execution_profile_sha256": PRODUCTION_EXECUTION_PROFILE_SHA256,
    }


def adapter_identity_sha256() -> str:
    """Return the canonical adapter identity and require registered authority."""

    if REGISTERED_W3_ORACLE_IDENTITY_SHA256 is None:
        raise W3OracleTrustError("W3 Oracle identity authority is unset")
    adapter = _registered_adapter()
    method_bindings_before = {
        name: _method_binding(adapter, name) for name in ("identity", "evaluate")
    }
    state_before = _instance_state(adapter)
    try:
        identity = _canonical_copy(adapter.identity(), "Oracle adapter identity")
    except AttributeError as error:
        raise W3OracleTrustError("Oracle adapter must expose canonical identity") from error
    state_after = _instance_state(adapter)
    method_bindings_after = {
        name: _method_binding(adapter, name) for name in ("identity", "evaluate")
    }
    if state_after != state_before:
        raise W3OracleTrustError("Oracle adapter identity lookup mutated instance state")
    if method_bindings_after != method_bindings_before:
        raise W3OracleTrustError("Oracle adapter identity lookup mutated callable bindings")
    if not isinstance(identity, dict) or not identity:
        raise W3OracleTrustError("Oracle adapter identity must be a non-empty object")
    base_identity_keys = {
        "schema_version",
        "adapter_id",
        "adapter_version",
        "toolchain_revision",
        "toolchain_tree",
        "language_version",
        "node",
        "node_path",
        "tsx_path",
        "runner_path",
        "node_binary_sha256",
        "runner_sha256",
        "tooling_package_sha256",
        "tooling_lock_sha256",
        "node_modules_sha256",
        "sandbox_exec_path",
        "sandbox_policy_version",
        "sandbox_policy_sha256",
        "class_module",
        "class_qualname",
        "code_file_sha256",
        "instance_state_sha256",
        "identity_method_module",
        "identity_method_qualname",
        "identity_method_source_file_sha256",
        "identity_method_code_sha256",
        "identity_method_defaults_sha256",
        "identity_method_kwdefaults_sha256",
        "identity_method_closure_sha256",
        "identity_method_callable_sha256",
        "evaluate_method_module",
        "evaluate_method_qualname",
        "evaluate_method_source_file_sha256",
        "evaluate_method_code_sha256",
        "evaluate_method_defaults_sha256",
        "evaluate_method_kwdefaults_sha256",
        "evaluate_method_closure_sha256",
        "evaluate_method_callable_sha256",
        "network_access",
        "metis_write",
    }
    production_identity_keys = {
        "receipt_mode",
        "runtime_bindings_sha256",
        "semantic_registry_sha256",
        "semantic_spec_schema_sha256",
        "oracle_protocol_sha256",
        "oracle_bridge_sha256",
        "oracle_result_schema_sha256",
        "source_register_schema_sha256",
        "w3_run_schema_sha256",
        "execution_profile_sha256",
    }
    schema_version = identity.get("schema_version")
    if schema_version == 1:
        _exact_keys(identity, base_identity_keys, "Oracle adapter identity")
    elif schema_version == 2:
        _exact_keys(
            identity,
            base_identity_keys | production_identity_keys,
            "Oracle adapter identity",
        )
    else:
        raise W3OracleTrustError("Oracle adapter identity schema is not pinned")
    for field in ("adapter_id", "adapter_version"):
        if not isinstance(identity[field], str) or not identity[field]:
            raise W3OracleTrustError(f"Oracle adapter identity {field} is missing")
    if (
        identity["toolchain_revision"] != PINNED_METIS_REVISION
        or identity["toolchain_tree"] != PINNED_METIS_TREE
        or identity["language_version"] != LANGUAGE_VERSION
        or identity["network_access"] != "disabled"
        or identity["metis_write"] != "forbidden"
        or identity["node"] != PINNED_NODE_VERSION
        or identity["node_path"] != NODE_RUNTIME_IDENTITY
        or identity["tsx_path"]
        != (
            f"snapshot://{PINNED_METIS_REVISION}/{PINNED_METIS_TREE}"
            "/tooling/node_modules/tsx/dist/loader.mjs"
        )
        or identity["runner_path"]
        != (f"snapshot://{PINNED_METIS_REVISION}/{PINNED_METIS_TREE}/.metis-oracle/runner.ts")
        or identity["node_binary_sha256"] != f"sha256:{PINNED_NODE_BINARY_SHA256}"
        or identity["runner_sha256"] != f"sha256:{PINNED_RUNNER_SHA256}"
        or identity["tooling_package_sha256"] != f"sha256:{PINNED_TOOLING_PACKAGE_SHA256}"
        or identity["tooling_lock_sha256"] != f"sha256:{PINNED_TOOLING_LOCK_SHA256}"
        or identity["node_modules_sha256"] != f"sha256:{PINNED_NODE_MODULES_SHA256}"
        or identity["sandbox_exec_path"] != SANDBOX_EXEC_IDENTITY
        or identity["sandbox_policy_version"] != SANDBOX_POLICY_VERSION
        or identity["sandbox_policy_sha256"] != f"sha256:{SANDBOX_POLICY_SHA256}"
    ):
        raise W3OracleTrustError("Oracle adapter toolchain/write/network identity is not pinned")
    if schema_version == 2:
        schema_dir = PROJECT_ROOT / "schemas"
        expected_production = {
            "semantic_spec_schema_sha256": _file_hash(schema_dir / "w3-semantic-spec.schema.json"),
            "oracle_protocol_sha256": _file_hash(Path(__file__).resolve()),
            "oracle_bridge_sha256": _file_hash(Path(__file__).with_name("oracles.py")),
            "oracle_result_schema_sha256": _file_hash(schema_dir / "oracle-result.schema.json"),
            "source_register_schema_sha256": _file_hash(
                schema_dir / "w3-source-register.schema.json"
            ),
            "w3_run_schema_sha256": _file_hash(schema_dir / "w3-run.schema.json"),
            "execution_profile_sha256": PRODUCTION_EXECUTION_PROFILE_SHA256,
            "runtime_bindings_sha256": _production_runtime_bindings_sha256(adapter),
        }
        if (
            identity["adapter_id"] != "metis-model1-w3-production"
            or identity["receipt_mode"] != "real-runner-envelopes"
            or not valid_hash(identity["semantic_registry_sha256"])
            or any(identity[field] != value for field, value in expected_production.items())
        ):
            raise W3OracleTrustError(
                "production adapter identity does not bind its transitive authorities"
            )
    for field in (
        "node_binary_sha256",
        "runner_sha256",
        "tooling_package_sha256",
        "tooling_lock_sha256",
        "node_modules_sha256",
        "sandbox_policy_sha256",
        "code_file_sha256",
        "instance_state_sha256",
        "identity_method_source_file_sha256",
        "identity_method_code_sha256",
        "identity_method_defaults_sha256",
        "identity_method_kwdefaults_sha256",
        "identity_method_closure_sha256",
        "identity_method_callable_sha256",
        "evaluate_method_source_file_sha256",
        "evaluate_method_code_sha256",
        "evaluate_method_defaults_sha256",
        "evaluate_method_kwdefaults_sha256",
        "evaluate_method_closure_sha256",
        "evaluate_method_callable_sha256",
        *(production_identity_keys - {"receipt_mode"}),
    ):
        if field in identity and not valid_hash(identity[field]):
            raise W3OracleTrustError(f"Oracle adapter identity {field} is not a sha256 pin")
    adapter_type = type(adapter)
    source_file = inspect.getsourcefile(adapter_type)
    if source_file is None:
        raise W3OracleTrustError("registered Oracle adapter class has no source file")
    try:
        source_path = Path(source_file).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise W3OracleTrustError("registered Oracle adapter source file is unavailable") from error
    if (
        identity["class_module"] != adapter_type.__module__
        or identity["class_qualname"] != adapter_type.__qualname__
        or identity["code_file_sha256"] != _file_hash(source_path)
        or identity["instance_state_sha256"] != canonical_hash(state_before)
    ):
        raise W3OracleTrustError(
            "Oracle adapter identity does not bind its actual class/code/instance state"
        )
    for name, binding in method_bindings_before.items():
        if any(identity[f"{name}_method_{field}"] != value for field, value in binding.items()):
            raise W3OracleTrustError(
                f"Oracle adapter identity does not bind actual {name} callable"
            )
    actual = canonical_hash(identity)
    if actual != REGISTERED_W3_ORACLE_IDENTITY_SHA256:
        raise W3OracleTrustError("Oracle adapter identity does not match registered authority")
    return actual


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extras = sorted(actual - expected)
        raise W3OracleTrustError(f"{label} keys mismatch: missing={missing} extras={extras}")


def _runtime_receipt(candidate_sha256: str, identity_sha256: str) -> dict[str, Any]:
    """Return the required runtime-policy binding, not proof of runner execution.

    A future production adapter remains separately reviewable and must obtain
    authority only after its real runner evidence has been audited. The module
    deliberately ships with no registered production adapter or identity.
    """

    body = {
        "schema_version": 1,
        "candidate_sha256": candidate_sha256,
        "adapter_identity_sha256": identity_sha256,
        "toolchain_revision": PINNED_METIS_REVISION,
        "toolchain_tree": PINNED_METIS_TREE,
        "node": PINNED_NODE_VERSION,
        "node_path": NODE_RUNTIME_IDENTITY,
        "tsx_path": (
            f"snapshot://{PINNED_METIS_REVISION}/{PINNED_METIS_TREE}"
            "/tooling/node_modules/tsx/dist/loader.mjs"
        ),
        "runner_path": (
            f"snapshot://{PINNED_METIS_REVISION}/{PINNED_METIS_TREE}/.metis-oracle/runner.ts"
        ),
        "node_binary_sha256": f"sha256:{PINNED_NODE_BINARY_SHA256}",
        "runner_sha256": f"sha256:{PINNED_RUNNER_SHA256}",
        "tooling_package_sha256": f"sha256:{PINNED_TOOLING_PACKAGE_SHA256}",
        "tooling_lock_sha256": f"sha256:{PINNED_TOOLING_LOCK_SHA256}",
        "node_modules_sha256": f"sha256:{PINNED_NODE_MODULES_SHA256}",
        "sandbox_exec_path": SANDBOX_EXEC_IDENTITY,
        "sandbox_policy_version": SANDBOX_POLICY_VERSION,
        "sandbox_policy_sha256": f"sha256:{SANDBOX_POLICY_SHA256}",
    }
    return {**body, "runtime_receipt_sha256": canonical_hash(body)}


def _validate_real_execution(
    value: Any,
    *,
    candidate: Mapping[str, Any],
    candidate_sha256: str,
    identity_sha256: str,
    role_contract: Mapping[str, str],
) -> None:
    if not isinstance(value, dict):
        raise W3OracleTrustError("real Oracle execution receipt must be an object")
    expected_keys = {
        "schema_version",
        "candidate_sha256",
        "adapter_identity_sha256",
        "semantic_spec_sha256",
        "execution_profile_sha256",
        "family",
        "role",
        "source_sha256",
        "request",
        "envelope",
        "artifact_path",
        "artifact_sha256",
        "result_sha256",
        "diagnostics_sha256",
        "ast_sha256",
        "ir_sha256",
        "runtime_sha256",
        "runtime_identity",
        "metis_status_sha256",
        "receipt_sha256",
    }
    _exact_keys(value, expected_keys, "real Oracle execution receipt")
    if value["schema_version"] != 1:
        raise W3OracleTrustError("real Oracle execution receipt schema is not pinned")
    role = role_contract["role"]
    source_field = role_contract["source_field"]
    source = candidate.get(source_field)
    if not isinstance(source, str) or not source:
        raise W3OracleTrustError(f"candidate source for role {role} is missing")
    expected_bindings = {
        "candidate_sha256": candidate_sha256,
        "adapter_identity_sha256": identity_sha256,
        "semantic_spec_sha256": candidate.get("semantic_spec_sha256"),
        "execution_profile_sha256": PRODUCTION_EXECUTION_PROFILE_SHA256,
        "family": candidate.get("family"),
        "role": role,
        "source_sha256": canonical_hash(source),
    }
    if any(value[field] != expected for field, expected in expected_bindings.items()):
        raise W3OracleTrustError("real Oracle execution receipt binding mismatch")
    request = value["request"]
    envelope = value["envelope"]
    semantic_spec = candidate.get("semantic_spec")
    if not isinstance(semantic_spec, dict):
        raise W3OracleTrustError("candidate semantic specification is missing")
    workspace_sources = semantic_spec.get("workspace_sources")
    if not isinstance(workspace_sources, dict):
        raise W3OracleTrustError("candidate workspace specification is invalid")
    workspace_payload = [
        {"filename": filename, "source": workspace_sources[filename]}
        for filename in sorted(workspace_sources)
    ]
    expected_request = {
        "schema_version": 1,
        "source": source,
        "filename": semantic_spec.get("filename"),
        "execution_mode": semantic_spec.get("execution_mode"),
        "endpoint": semantic_spec.get("endpoint"),
        "metis_root": f"snapshot://{PINNED_METIS_REVISION}/{PINNED_METIS_TREE}",
        "metis_revision": PINNED_METIS_REVISION,
        "metis_tree": PINNED_METIS_TREE,
        "workspace_sources": workspace_payload,
    }
    if not isinstance(request, dict) or request != expected_request:
        raise W3OracleTrustError("real Oracle request is not the exact registered request")
    try:
        verify_oracle_envelope(envelope, request=request)
    except ValueError as error:
        raise W3OracleTrustError("real Oracle envelope failed independent verification") from error
    result = envelope["result"]
    evidence = envelope["evidence"]
    expected_evidence = {
        "result_sha256": canonical_hash(result),
        "diagnostics_sha256": evidence["diagnostics_sha256"],
        "ast_sha256": evidence["ast_sha256"],
        "ir_sha256": evidence["ir_sha256"],
        "runtime_sha256": evidence["runtime_sha256"],
        "runtime_identity": evidence["runtime_identity"],
        "metis_status_sha256": evidence["metis_status_sha256"],
    }
    if any(value[field] != expected for field, expected in expected_evidence.items()):
        raise W3OracleTrustError("real Oracle receipt evidence hash mismatch")
    if result["status"] != role_contract["expected_status"]:
        raise W3CandidateRejected(f"Oracle role {role} returned unexpected status")
    artifact_path = value["artifact_path"]
    artifact = Path(artifact_path) if isinstance(artifact_path, str) else Path("")
    if (
        not isinstance(artifact_path, str)
        or artifact.is_absolute()
        or ".." in artifact.parts
        or artifact.suffix != ".json"
        or artifact.parts[:2] != ("artifacts", "w3-production")
    ):
        raise W3OracleTrustError("real Oracle artifact path is not safe and project-relative")
    artifact_root_path = PROJECT_ROOT / "artifacts" / "w3-production"
    unresolved_artifact = PROJECT_ROOT / artifact
    checked_paths = [
        PROJECT_ROOT / "artifacts",
        artifact_root_path,
        *[
            parent
            for parent in unresolved_artifact.parents
            if parent != PROJECT_ROOT and artifact_root_path in (parent, *parent.parents)
        ],
        unresolved_artifact,
    ]
    if any(path.is_symlink() for path in checked_paths):
        raise W3OracleTrustError("real Oracle artifact path contains a symlink")
    try:
        artifact_root = artifact_root_path.resolve(strict=True)
        materialized = unresolved_artifact.resolve(strict=True)
        materialized.relative_to(artifact_root)
        artifact_bytes = materialized.read_bytes()
    except (OSError, RuntimeError, ValueError) as error:
        raise W3OracleTrustError(
            "real Oracle artifact is unavailable or outside its root"
        ) from error
    if materialized.is_symlink() or not materialized.is_file():
        raise W3OracleTrustError("real Oracle artifact must be a regular file")
    if artifact_bytes != canonical_json_bytes(envelope):
        raise W3OracleTrustError("real Oracle artifact bytes do not match its envelope")
    if value["artifact_sha256"] != SHA256_PREFIX + hashlib.sha256(artifact_bytes).hexdigest():
        raise W3OracleTrustError("real Oracle artifact hash mismatch")
    body = {field: item for field, item in value.items() if field != "receipt_sha256"}
    if value["receipt_sha256"] != canonical_hash(body):
        raise W3OracleTrustError("real Oracle execution receipt hash mismatch")


def _validate_real_runtime_receipt(
    value: dict[str, Any],
    *,
    candidate: Mapping[str, Any],
    candidate_sha256: str,
    identity_sha256: str,
    expected_registry_sha256: str,
) -> None:
    expected_keys = {
        "schema_version",
        "receipt_mode",
        "candidate_sha256",
        "adapter_identity_sha256",
        "semantic_registry_sha256",
        "semantic_spec_sha256",
        "execution_profile_sha256",
        "executions",
        "runtime_receipt_sha256",
    }
    _exact_keys(value, expected_keys, "real Oracle runtime receipt")
    if value["schema_version"] != 2 or value["receipt_mode"] != "real-runner-envelopes":
        raise W3OracleTrustError("real Oracle runtime receipt schema/mode is not pinned")
    if (
        value["candidate_sha256"] != candidate_sha256
        or value["adapter_identity_sha256"] != identity_sha256
        or value["semantic_spec_sha256"] != candidate.get("semantic_spec_sha256")
        or value["execution_profile_sha256"] != PRODUCTION_EXECUTION_PROFILE_SHA256
        or value["semantic_registry_sha256"] != expected_registry_sha256
    ):
        raise W3OracleTrustError("real Oracle runtime receipt authority binding mismatch")
    profile = production_execution_profile()
    role_contracts = profile["roles"][candidate["family"]]
    executions = value["executions"]
    if not isinstance(executions, list) or len(executions) != len(role_contracts):
        raise W3OracleTrustError("real Oracle runtime receipt role roster mismatch")
    for execution, role_contract in zip(executions, role_contracts, strict=True):
        _validate_real_execution(
            execution,
            candidate=candidate,
            candidate_sha256=candidate_sha256,
            identity_sha256=identity_sha256,
            role_contract=role_contract,
        )
    body = {field: item for field, item in value.items() if field != "runtime_receipt_sha256"}
    if value["runtime_receipt_sha256"] != canonical_hash(body):
        raise W3OracleTrustError("real Oracle runtime receipt hash mismatch")


def _validate_runtime_receipt(
    value: Any,
    candidate_sha256: str,
    identity_sha256: str,
    *,
    candidate: Mapping[str, Any],
    require_real: bool,
    expected_registry_sha256: str | None = None,
) -> None:
    if not isinstance(value, dict):
        raise W3OracleError("Oracle runtime receipt must be an object")
    if require_real:
        if not valid_hash(expected_registry_sha256):
            raise W3OracleTrustError("production adapter registry identity is missing")
        _validate_real_runtime_receipt(
            value,
            candidate=candidate,
            candidate_sha256=candidate_sha256,
            identity_sha256=identity_sha256,
            expected_registry_sha256=expected_registry_sha256,
        )
        return
    expected = _runtime_receipt(candidate_sha256, identity_sha256)
    _exact_keys(value, set(expected), "Oracle runtime receipt")
    if value != expected:
        raise W3OracleError(
            "Oracle runtime receipt is not bound to candidate/adapter/toolchain pins"
        )


def invoke_oracle(candidate: Mapping[str, Any]) -> OracleEvaluation:
    """Invoke and validate the registered adapter for one canonical candidate."""

    if not isinstance(candidate, Mapping):
        raise W3OracleError("candidate must be an object")
    canonical_candidate = _canonical_copy(dict(candidate), "candidate")
    family = canonical_candidate.get("family")
    if not isinstance(family, str):
        raise W3OracleError("candidate family is missing")
    predicates_required = required_predicates(family)
    adapter = _registered_adapter()
    identity_sha256 = adapter_identity_sha256()
    candidate_sha256 = canonical_hash(canonical_candidate)
    adapter_input = _canonical_copy(canonical_candidate, "candidate")
    evaluation_error: Exception | None = None
    evaluated: Any = None
    try:
        evaluated = adapter.evaluate(adapter_input)
    except Exception as error:
        evaluation_error = error
    try:
        post_identity_sha256 = adapter_identity_sha256()
    except W3OracleError as error:
        raise W3OracleTrustError(
            "registered Oracle adapter identity/state changed during evaluation"
        ) from error
    if post_identity_sha256 != identity_sha256:
        raise W3OracleTrustError("registered Oracle adapter identity changed during evaluation")
    if evaluation_error is not None:
        if isinstance(evaluation_error, W3OracleError):
            raise evaluation_error
        raise W3OracleInfrastructureError(
            f"Oracle adapter failed closed: {type(evaluation_error).__name__}"
        ) from evaluation_error
    try:
        identity_material = _canonical_copy(adapter.identity(), "Oracle adapter identity")
    except Exception as error:
        raise W3OracleTrustError(
            "Oracle adapter identity is unavailable after evaluation"
        ) from error
    if (
        not isinstance(identity_material, dict)
        or canonical_hash(identity_material) != identity_sha256
    ):
        raise W3OracleTrustError("Oracle adapter identity changed after evaluation")
    raw = _canonical_copy(evaluated, "Oracle result")
    if not isinstance(raw, dict):
        raise W3OracleError("Oracle result must be an object")
    _exact_keys(
        raw,
        {
            "schema_version",
            "status",
            "family",
            "candidate_sha256",
            "adapter_identity_sha256",
            "receipt_mode",
            "runtime_receipt",
            "predicates",
            "evidence",
        },
        "Oracle result",
    )
    if raw["schema_version"] != 1 or raw["family"] != family:
        raise W3OracleError("Oracle status/schema/family is not an exact pass")
    if raw["status"] == "fail":
        raise W3CandidateRejected("Oracle status/schema/family is not an exact pass")
    if raw["status"] != "pass":
        raise W3OracleTrustError("Oracle status/schema/family is not an exact pass")
    if raw["candidate_sha256"] != candidate_sha256:
        raise W3OracleError("Oracle result is not bound to the canonical candidate")
    if raw["adapter_identity_sha256"] != identity_sha256:
        raise W3OracleError("Oracle result is not bound to the registered adapter")
    expected_receipt_mode = (
        "real-runner-envelopes"
        if identity_material.get("schema_version") == 2
        else "fixture-policy"
    )
    if raw["receipt_mode"] != expected_receipt_mode:
        raise W3OracleTrustError("Oracle result receipt mode does not match adapter authority")
    _validate_runtime_receipt(
        raw["runtime_receipt"],
        candidate_sha256,
        identity_sha256,
        candidate=canonical_candidate,
        require_real=identity_material.get("schema_version") == 2,
        expected_registry_sha256=identity_material.get("semantic_registry_sha256"),
    )
    predicates = raw["predicates"]
    evidence = raw["evidence"]
    if not isinstance(predicates, dict) or not isinstance(evidence, dict):
        raise W3OracleError("Oracle predicates and evidence must be objects")
    _exact_keys(predicates, set(predicates_required), "Oracle predicates")
    _exact_keys(evidence, {*predicates_required, "ast", "ir", "binding"}, "Oracle evidence")
    if any(type(predicates[name]) is not bool for name in predicates_required):
        raise W3OracleError("Oracle predicates must be booleans")
    if not all(predicates[name] for name in predicates_required):
        raise W3OracleError("one or more required Oracle predicates failed")
    for name in predicates_required:
        if not isinstance(evidence[name], dict) or not evidence[name]:
            raise W3OracleError(f"Oracle evidence {name} must be a non-empty object")
    binding = evidence["binding"]
    if not isinstance(binding, dict):
        raise W3OracleError("Oracle binding evidence must be an object")
    _exact_keys(
        binding,
        {"candidate_sha256", "content_sha256", "semantic_spec_sha256"},
        "Oracle binding",
    )
    if binding["candidate_sha256"] != candidate_sha256:
        raise W3OracleError("Oracle binding candidate hash mismatch")
    for field in ("content_sha256", "semantic_spec_sha256"):
        expected = canonical_candidate.get(field)
        if not valid_hash(expected) or binding[field] != expected:
            raise W3OracleError(f"Oracle binding {field} mismatch")
    for name in ("ast", "ir"):
        structural = evidence[name]
        if not isinstance(structural, dict) or set(structural) != {"signature", "evidence"}:
            raise W3OracleError(f"Oracle {name} evidence shape is invalid")
        if not valid_hash(structural["signature"]) or not isinstance(structural["evidence"], dict):
            raise W3OracleError(f"Oracle {name} signature/evidence is invalid")
        if not structural["evidence"]:
            raise W3OracleError(f"Oracle {name} evidence must not be empty")
        if structural["evidence"].get("candidate_sha256") != candidate_sha256:
            raise W3OracleError(f"Oracle {name} evidence is not candidate-bound")
    for name in ("parse", "link", "validate", "compile"):
        material = evidence[name]
        _exact_keys(material, {"candidate_sha256", "details"}, f"Oracle {name} evidence")
        if material["candidate_sha256"] != candidate_sha256:
            raise W3OracleError(f"Oracle {name} evidence is not candidate-bound")
        if not isinstance(material["details"], dict) or not material["details"]:
            raise W3OracleError(f"Oracle {name} details must be non-empty")
    semantic = evidence["semantic"]
    _exact_keys(
        semantic,
        {"candidate_sha256", "semantic_spec_sha256", "details"},
        "Oracle semantic evidence",
    )
    if (
        semantic["candidate_sha256"] != candidate_sha256
        or semantic["semantic_spec_sha256"] != canonical_candidate["semantic_spec_sha256"]
    ):
        raise W3OracleError("Oracle semantic evidence is not spec-bound")
    if not isinstance(semantic["details"], dict) or not semantic["details"]:
        raise W3OracleError("Oracle semantic details must be non-empty")
    if semantic["details"].get("matched") is not True:
        raise W3OracleError("Oracle semantic evidence contradicts its pass predicate")
    if family == "F-2":
        minimality = evidence["patch_minimality"]
        _exact_keys(
            minimality,
            {
                "candidate_sha256",
                "before_sha256",
                "after_sha256",
                "delta_sha256",
                "details",
            },
            "Oracle patch_minimality evidence",
        )
        delta_key = "expected_delta" if "expected_delta" in canonical_candidate else "patch"
        expected = {
            "candidate_sha256": candidate_sha256,
            "before_sha256": canonical_hash(canonical_candidate["before_source"]),
            "after_sha256": canonical_hash(canonical_candidate["after_source"]),
            "delta_sha256": canonical_hash(canonical_candidate[delta_key]),
        }
        if any(minimality[field] != value for field, value in expected.items()):
            raise W3OracleError("Oracle patch_minimality evidence is not edit-bound")
        if not isinstance(minimality["details"], dict) or not minimality["details"]:
            raise W3OracleError("Oracle patch_minimality details must be non-empty")
        if minimality["details"].get("minimal") is not True:
            raise W3OracleError("Oracle patch_minimality evidence is not an exact pass")
    if family == "F-3":
        diagnostic = evidence["diagnostic"]
        _exact_keys(
            diagnostic,
            {
                "candidate_sha256",
                "mutated_sha256",
                "fixed_sha256",
                "expected_diagnostic_sha256",
                "mutation_spec_sha256",
                "details",
            },
            "Oracle diagnostic evidence",
        )
        expected = {
            "candidate_sha256": candidate_sha256,
            "mutated_sha256": canonical_hash(canonical_candidate["mutated_source"]),
            "fixed_sha256": canonical_hash(canonical_candidate["fixed_source"]),
            "expected_diagnostic_sha256": canonical_hash(
                canonical_candidate["expected_diagnostic"]
            ),
            "mutation_spec_sha256": canonical_hash(canonical_candidate["mutation_spec"]),
        }
        if any(diagnostic[field] != value for field, value in expected.items()):
            raise W3OracleError("Oracle diagnostic evidence is not repair-bound")
        if not isinstance(diagnostic["details"], dict) or not diagnostic["details"]:
            raise W3OracleError("Oracle diagnostic details must be non-empty")
        if diagnostic["details"].get("repaired") is not True:
            raise W3OracleError("Oracle diagnostic evidence is not an exact repair pass")
    envelope = _canonical_copy(raw, "Oracle result")
    return OracleEvaluation(
        envelope=envelope,
        oracle_result_sha256=canonical_hash(envelope),
        semantic_result_sha256=canonical_hash(envelope["evidence"]["semantic"]),
        ast_sha256=envelope["evidence"]["ast"]["signature"],
        ir_sha256=envelope["evidence"]["ir"]["signature"],
    )


__all__ = [
    "OracleAdapter",
    "OracleEvaluation",
    "PINNED_METIS_REVISION",
    "PRODUCTION_EXECUTION_PROFILE_SHA256",
    "REGISTERED_W3_ORACLE_ADAPTER",
    "REGISTERED_W3_ORACLE_IDENTITY_SHA256",
    "W3CandidateRejected",
    "W3OracleError",
    "W3OracleInfrastructureError",
    "W3OracleTrustError",
    "adapter_identity_sha256",
    "canonical_hash",
    "invoke_oracle",
    "production_adapter_identity",
    "production_execution_profile",
    "required_predicates",
    "stable_code_sha256",
    "valid_hash",
]
