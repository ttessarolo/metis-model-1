"""Registered, fail-closed Oracle Protocol for W3.

An adapter is not trusted because a caller supplied it. Its canonical identity
must match the module authority registered by the frontier coordinator, and
every result is bound to the exact canonical candidate evaluated.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import marshal
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
)
from metis_model1.provenance import canonical_json_bytes

REGISTERED_W3_ORACLE_IDENTITY_SHA256: str | None = None
REGISTERED_W3_ORACLE_ADAPTER: OracleAdapter | None = None
SHA256_PREFIX = "sha256:"
PINNED_METIS_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
LANGUAGE_VERSION = "0.43"


class W3OracleError(ValueError):
    """Raised when the registered Oracle contract is not satisfied exactly."""


class OracleAdapter(Protocol):
    """Independent adapter boundary used by the W3 builder."""

    def identity(self) -> Mapping[str, Any]:
        """Return immutable adapter/toolchain identity material."""

    def evaluate(self, candidate: Mapping[str, Any]) -> Mapping[str, Any]:
        """Evaluate one canonical candidate without network or repository writes."""


def canonical_hash(value: Any) -> str:
    return SHA256_PREFIX + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


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


def _registered_adapter() -> OracleAdapter:
    if REGISTERED_W3_ORACLE_ADAPTER is None:
        raise W3OracleError("W3 Oracle adapter authority is unset")
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
    code_sha256 = SHA256_PREFIX + hashlib.sha256(marshal.dumps(class_callable.__code__)).hexdigest()
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


def adapter_identity_sha256() -> str:
    """Return the canonical adapter identity and require registered authority."""

    if REGISTERED_W3_ORACLE_IDENTITY_SHA256 is None:
        raise W3OracleError("W3 Oracle identity authority is unset")
    adapter = _registered_adapter()
    method_bindings_before = {
        name: _method_binding(adapter, name) for name in ("identity", "evaluate")
    }
    state_before = _instance_state(adapter)
    try:
        identity = _canonical_copy(adapter.identity(), "Oracle adapter identity")
    except AttributeError as error:
        raise W3OracleError("Oracle adapter must expose canonical identity") from error
    state_after = _instance_state(adapter)
    method_bindings_after = {
        name: _method_binding(adapter, name) for name in ("identity", "evaluate")
    }
    if state_after != state_before:
        raise W3OracleError("Oracle adapter identity lookup mutated instance state")
    if method_bindings_after != method_bindings_before:
        raise W3OracleError("Oracle adapter identity lookup mutated callable bindings")
    if not isinstance(identity, dict) or not identity:
        raise W3OracleError("Oracle adapter identity must be a non-empty object")
    _exact_keys(
        identity,
        {
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
        },
        "Oracle adapter identity",
    )
    if identity["schema_version"] != 1:
        raise W3OracleError("Oracle adapter identity schema is not pinned")
    for field in ("adapter_id", "adapter_version"):
        if not isinstance(identity[field], str) or not identity[field]:
            raise W3OracleError(f"Oracle adapter identity {field} is missing")
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
        raise W3OracleError("Oracle adapter toolchain/write/network identity is not pinned")
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
    ):
        if not valid_hash(identity[field]):
            raise W3OracleError(f"Oracle adapter identity {field} is not a sha256 pin")
    adapter_type = type(adapter)
    source_file = inspect.getsourcefile(adapter_type)
    if source_file is None:
        raise W3OracleError("registered Oracle adapter class has no source file")
    try:
        source_path = Path(source_file).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise W3OracleError("registered Oracle adapter source file is unavailable") from error
    if (
        identity["class_module"] != adapter_type.__module__
        or identity["class_qualname"] != adapter_type.__qualname__
        or identity["code_file_sha256"] != _file_hash(source_path)
        or identity["instance_state_sha256"] != canonical_hash(state_before)
    ):
        raise W3OracleError(
            "Oracle adapter identity does not bind its actual class/code/instance state"
        )
    for name, binding in method_bindings_before.items():
        if any(identity[f"{name}_method_{field}"] != value for field, value in binding.items()):
            raise W3OracleError(f"Oracle adapter identity does not bind actual {name} callable")
    actual = canonical_hash(identity)
    if actual != REGISTERED_W3_ORACLE_IDENTITY_SHA256:
        raise W3OracleError("Oracle adapter identity does not match registered authority")
    return actual


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extras = sorted(actual - expected)
        raise W3OracleError(f"{label} keys mismatch: missing={missing} extras={extras}")


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


def _validate_runtime_receipt(value: Any, candidate_sha256: str, identity_sha256: str) -> None:
    if not isinstance(value, dict):
        raise W3OracleError("Oracle runtime receipt must be an object")
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
        raise W3OracleError(
            "registered Oracle adapter identity/state changed during evaluation"
        ) from error
    if post_identity_sha256 != identity_sha256:
        raise W3OracleError("registered Oracle adapter identity changed during evaluation")
    if evaluation_error is not None:
        if isinstance(evaluation_error, W3OracleError):
            raise evaluation_error
        raise W3OracleError(
            f"Oracle adapter failed closed: {type(evaluation_error).__name__}"
        ) from evaluation_error
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
            "runtime_receipt",
            "predicates",
            "evidence",
        },
        "Oracle result",
    )
    if raw["schema_version"] != 1 or raw["status"] != "pass" or raw["family"] != family:
        raise W3OracleError("Oracle status/schema/family is not an exact pass")
    if raw["candidate_sha256"] != candidate_sha256:
        raise W3OracleError("Oracle result is not bound to the canonical candidate")
    if raw["adapter_identity_sha256"] != identity_sha256:
        raise W3OracleError("Oracle result is not bound to the registered adapter")
    _validate_runtime_receipt(raw["runtime_receipt"], candidate_sha256, identity_sha256)
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
    "REGISTERED_W3_ORACLE_ADAPTER",
    "REGISTERED_W3_ORACLE_IDENTITY_SHA256",
    "W3OracleError",
    "adapter_identity_sha256",
    "canonical_hash",
    "invoke_oracle",
    "required_predicates",
    "valid_hash",
]
