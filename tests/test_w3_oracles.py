from __future__ import annotations

import hashlib
import inspect
import marshal
from pathlib import Path

import pytest

import metis_model1.w3_oracles as oracle_module
from metis_model1.w3_oracles import (
    PINNED_METIS_REVISION,
    W3OracleError,
    canonical_hash,
    invoke_oracle,
    required_predicates,
)


def _file_hash(path: str) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _identity(adapter: object) -> dict:
    adapter_type = type(adapter)
    source = inspect.getsourcefile(adapter_type)
    assert source is not None
    method_identity: dict[str, str] = {}
    for name in ("identity", "evaluate"):
        method = inspect.getattr_static(adapter_type, name)
        assert inspect.isfunction(method)
        method_source = inspect.getsourcefile(method)
        assert method_source is not None
        defaults_sha = canonical_hash(
            None if method.__defaults__ is None else list(method.__defaults__)
        )
        kwdefaults_sha = canonical_hash(method.__kwdefaults__)
        closure_sha = canonical_hash(
            None
            if method.__closure__ is None
            else [cell.cell_contents for cell in method.__closure__]
        )
        code_sha = "sha256:" + hashlib.sha256(marshal.dumps(method.__code__)).hexdigest()
        callable_sha = canonical_hash(
            {
                "code_sha256": code_sha,
                "defaults_sha256": defaults_sha,
                "kwdefaults_sha256": kwdefaults_sha,
                "closure_sha256": closure_sha,
            }
        )
        method_identity.update(
            {
                f"{name}_method_module": method.__module__,
                f"{name}_method_qualname": method.__qualname__,
                f"{name}_method_source_file_sha256": _file_hash(method_source),
                f"{name}_method_code_sha256": code_sha,
                f"{name}_method_defaults_sha256": defaults_sha,
                f"{name}_method_kwdefaults_sha256": kwdefaults_sha,
                f"{name}_method_closure_sha256": closure_sha,
                f"{name}_method_callable_sha256": callable_sha,
            }
        )
    return {
        "schema_version": 1,
        "adapter_id": "registered-test-oracle",
        "adapter_version": "1",
        "toolchain_revision": PINNED_METIS_REVISION,
        "toolchain_tree": oracle_module.PINNED_METIS_TREE,
        "language_version": "0.43",
        "node": oracle_module.PINNED_NODE_VERSION,
        "node_path": oracle_module.NODE_RUNTIME_IDENTITY,
        "tsx_path": (
            f"snapshot://{PINNED_METIS_REVISION}/{oracle_module.PINNED_METIS_TREE}"
            "/tooling/node_modules/tsx/dist/loader.mjs"
        ),
        "runner_path": (
            f"snapshot://{PINNED_METIS_REVISION}/{oracle_module.PINNED_METIS_TREE}"
            "/.metis-oracle/runner.ts"
        ),
        "node_binary_sha256": f"sha256:{oracle_module.PINNED_NODE_BINARY_SHA256}",
        "runner_sha256": f"sha256:{oracle_module.PINNED_RUNNER_SHA256}",
        "tooling_package_sha256": f"sha256:{oracle_module.PINNED_TOOLING_PACKAGE_SHA256}",
        "tooling_lock_sha256": f"sha256:{oracle_module.PINNED_TOOLING_LOCK_SHA256}",
        "node_modules_sha256": f"sha256:{oracle_module.PINNED_NODE_MODULES_SHA256}",
        "sandbox_exec_path": oracle_module.SANDBOX_EXEC_IDENTITY,
        "sandbox_policy_version": oracle_module.SANDBOX_POLICY_VERSION,
        "sandbox_policy_sha256": f"sha256:{oracle_module.SANDBOX_POLICY_SHA256}",
        "class_module": adapter_type.__module__,
        "class_qualname": adapter_type.__qualname__,
        "code_file_sha256": _file_hash(source),
        "instance_state_sha256": canonical_hash(vars(adapter)),
        **method_identity,
        "network_access": "disabled",
        "metis_write": "forbidden",
    }


def _runtime_receipt(candidate_sha: str, identity_sha: str) -> dict:
    # Fixture-only runtime-policy binding; this is not evidence of real runner execution.
    body = {
        "schema_version": 1,
        "candidate_sha256": candidate_sha,
        "adapter_identity_sha256": identity_sha,
        "toolchain_revision": PINNED_METIS_REVISION,
        "toolchain_tree": oracle_module.PINNED_METIS_TREE,
        "node": oracle_module.PINNED_NODE_VERSION,
        "node_path": oracle_module.NODE_RUNTIME_IDENTITY,
        "tsx_path": (
            f"snapshot://{PINNED_METIS_REVISION}/{oracle_module.PINNED_METIS_TREE}"
            "/tooling/node_modules/tsx/dist/loader.mjs"
        ),
        "runner_path": (
            f"snapshot://{PINNED_METIS_REVISION}/{oracle_module.PINNED_METIS_TREE}"
            "/.metis-oracle/runner.ts"
        ),
        "node_binary_sha256": f"sha256:{oracle_module.PINNED_NODE_BINARY_SHA256}",
        "runner_sha256": f"sha256:{oracle_module.PINNED_RUNNER_SHA256}",
        "tooling_package_sha256": f"sha256:{oracle_module.PINNED_TOOLING_PACKAGE_SHA256}",
        "tooling_lock_sha256": f"sha256:{oracle_module.PINNED_TOOLING_LOCK_SHA256}",
        "node_modules_sha256": f"sha256:{oracle_module.PINNED_NODE_MODULES_SHA256}",
        "sandbox_exec_path": oracle_module.SANDBOX_EXEC_IDENTITY,
        "sandbox_policy_version": oracle_module.SANDBOX_POLICY_VERSION,
        "sandbox_policy_sha256": f"sha256:{oracle_module.SANDBOX_POLICY_SHA256}",
    }
    return {**body, "runtime_receipt_sha256": canonical_hash(body)}


def oracle_candidate(family: str = "F-1") -> dict:
    common = {
        "candidate_id": f"candidate-{family}",
        "family": family,
        "split": "train",
        "semantic_spec": {"intent": family},
        "root_evidence": {},
        "rights": {},
        "parents": [],
        "content_sha256": canonical_hash({"content": family}),
        "semantic_spec_sha256": canonical_hash({"intent": family}),
        "component_roots": [canonical_hash({"root": family})],
        "leakage_group": canonical_hash({"group": family}),
    }
    if family == "F-1":
        return {**common, "request": "author", "target_source": "property x { value: 1 }"}
    if family == "F-2":
        return {
            **common,
            "before_source": "property x { value: 1 }",
            "after_source": "property x { value: 2 }",
            "expected_delta": {"replace": ["1", "2"]},
        }
    return {
        **common,
        "mutated_source": "property x { value: }",
        "expected_diagnostic": {"code": "missing-value"},
        "fixed_source": "property x { value: 1 }",
        "mutation_spec": {"remove": "1"},
    }


class RegisteredFakeAdapter:
    def __init__(self, *, mutation: str | None = None, ast_signature: str | None = None) -> None:
        self.mutation = mutation
        self.ast_signature = ast_signature

    def identity(self) -> dict:
        return _identity(self)

    def evaluate(self, candidate: dict) -> dict:
        candidate_sha = canonical_hash(candidate)
        identity_sha = canonical_hash(self.identity())
        predicates = required_predicates(candidate["family"])
        evidence = {
            name: {"candidate_sha256": candidate_sha, "details": {"oracle": name}}
            for name in ("parse", "link", "validate", "compile")
        }
        evidence["semantic"] = {
            "candidate_sha256": candidate_sha,
            "semantic_spec_sha256": candidate["semantic_spec_sha256"],
            "details": {"matched": True},
        }
        if candidate["family"] == "F-2":
            delta_key = "expected_delta" if "expected_delta" in candidate else "patch"
            evidence["patch_minimality"] = {
                "candidate_sha256": candidate_sha,
                "before_sha256": canonical_hash(candidate["before_source"]),
                "after_sha256": canonical_hash(candidate["after_source"]),
                "delta_sha256": canonical_hash(candidate[delta_key]),
                "details": {"minimal": True},
            }
        if candidate["family"] == "F-3":
            evidence["diagnostic"] = {
                "candidate_sha256": candidate_sha,
                "mutated_sha256": canonical_hash(candidate["mutated_source"]),
                "fixed_sha256": canonical_hash(candidate["fixed_source"]),
                "expected_diagnostic_sha256": canonical_hash(candidate["expected_diagnostic"]),
                "mutation_spec_sha256": canonical_hash(candidate["mutation_spec"]),
                "details": {"repaired": True},
            }
        evidence["ast"] = {
            "signature": self.ast_signature or canonical_hash({"ast": candidate_sha}),
            "evidence": {"candidate_sha256": candidate_sha},
        }
        evidence["ir"] = {
            "signature": canonical_hash({"ir": candidate_sha}),
            "evidence": {"candidate_sha256": candidate_sha},
        }
        evidence["binding"] = {
            "candidate_sha256": candidate_sha,
            "content_sha256": candidate["content_sha256"],
            "semantic_spec_sha256": candidate["semantic_spec_sha256"],
        }
        result = {
            "schema_version": 1,
            "status": "pass",
            "family": candidate["family"],
            "candidate_sha256": candidate_sha,
            "adapter_identity_sha256": identity_sha,
            "runtime_receipt": _runtime_receipt(candidate_sha, identity_sha),
            "predicates": {name: True for name in predicates},
            "evidence": evidence,
        }
        if self.mutation == "extra_result":
            result["extra"] = True
        elif self.mutation == "extra_predicates":
            result["predicates"]["extra"] = True
        elif self.mutation == "extra_evidence":
            result["evidence"]["extra"] = {"forged": True}
        elif self.mutation == "pending":
            result["status"] = "pending"
        elif self.mutation == "missing_semantic":
            result["predicates"].pop("semantic")
        elif self.mutation == "false_semantic":
            result["predicates"]["semantic"] = False
        elif self.mutation == "semantic_contradiction":
            result["evidence"]["semantic"]["details"]["matched"] = False
        elif self.mutation == "minimality_contradiction":
            result["evidence"]["patch_minimality"]["details"]["minimal"] = False
        elif self.mutation == "diagnostic_not_repaired":
            result["evidence"]["diagnostic"]["details"]["repaired"] = False
        elif self.mutation == "forged_binding":
            result["evidence"]["binding"]["candidate_sha256"] = canonical_hash("forged")
        elif self.mutation == "wrong_diagnostic":
            result["evidence"]["diagnostic"]["expected_diagnostic_sha256"] = canonical_hash("wrong")
        elif self.mutation == "change_evidence":
            result["evidence"]["semantic"]["details"] = {
                "matched": True,
                "review": "second",
            }
        elif self.mutation == "missing_receipt":
            result.pop("runtime_receipt")
        elif self.mutation == "extra_receipt":
            result["runtime_receipt"]["extra"] = True
        elif self.mutation == "forged_receipt_candidate":
            receipt = result["runtime_receipt"]
            receipt["candidate_sha256"] = canonical_hash("forged")
            receipt_body = {
                key: value for key, value in receipt.items() if key != "runtime_receipt_sha256"
            }
            receipt["runtime_receipt_sha256"] = canonical_hash(receipt_body)
        elif self.mutation == "forged_receipt_pin":
            receipt = result["runtime_receipt"]
            receipt["runner_sha256"] = canonical_hash("forged-runner")
            receipt_body = {
                key: value for key, value in receipt.items() if key != "runtime_receipt_sha256"
            }
            receipt["runtime_receipt_sha256"] = canonical_hash(receipt_body)
        elif self.mutation == "tampered_receipt_hash":
            result["runtime_receipt"]["runtime_receipt_sha256"] = canonical_hash("tampered")
        elif self.mutation == "mutate_instance_state":
            self.ast_signature = canonical_hash("mutated-during-evaluate")
        return result


def register(monkeypatch: pytest.MonkeyPatch, adapter: RegisteredFakeAdapter) -> None:
    identity = adapter.identity()
    monkeypatch.setattr(oracle_module, "REGISTERED_W3_ORACLE_ADAPTER", adapter)
    monkeypatch.setattr(
        oracle_module, "REGISTERED_W3_ORACLE_IDENTITY_SHA256", canonical_hash(identity)
    )


@pytest.fixture(autouse=True)
def registered_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    register(monkeypatch, RegisteredFakeAdapter())


@pytest.mark.parametrize("family", ["F-1", "F-2", "F-3"])
def test_registered_protocol_binds_each_family(family: str) -> None:
    evaluation = invoke_oracle(oracle_candidate(family))
    assert evaluation.envelope["family"] == family
    assert evaluation.oracle_result_sha256 == canonical_hash(evaluation.envelope)
    assert set(evaluation.predicates) == set(required_predicates(family))
    assert (
        evaluation.envelope["runtime_receipt"]["candidate_sha256"]
        == evaluation.envelope["candidate_sha256"]
    )


def test_public_oracle_has_no_caller_adapter_and_unset_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert "adapter" not in inspect.signature(invoke_oracle).parameters
    assert not hasattr(oracle_module, "make_static_adapter")
    monkeypatch.setattr(oracle_module, "REGISTERED_W3_ORACLE_ADAPTER", None)
    with pytest.raises(W3OracleError, match="adapter authority is unset"):
        invoke_oracle(oracle_candidate())


def test_wrong_registered_class_code_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    original = RegisteredFakeAdapter()

    class ClonedIdentityAdapter(RegisteredFakeAdapter):
        def identity(self) -> dict:
            return dict(self.claimed_identity)

    clone = ClonedIdentityAdapter()
    clone.claimed_identity = original.identity()
    monkeypatch.setattr(oracle_module, "REGISTERED_W3_ORACLE_ADAPTER", clone)
    monkeypatch.setattr(
        oracle_module,
        "REGISTERED_W3_ORACLE_IDENTITY_SHA256",
        canonical_hash(clone.identity()),
    )
    with pytest.raises(W3OracleError, match="actual class/code"):
        invoke_oracle(oracle_candidate())


def test_exact_configured_instance_accepts_and_same_class_config_swap_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered = RegisteredFakeAdapter(ast_signature=canonical_hash("registered-config"))
    register(monkeypatch, registered)
    evaluation = invoke_oracle(oracle_candidate())
    assert evaluation.ast_sha256 == registered.ast_signature

    clone = RegisteredFakeAdapter(ast_signature=canonical_hash("different-config"))
    monkeypatch.setattr(oracle_module, "REGISTERED_W3_ORACLE_ADAPTER", clone)
    with pytest.raises(W3OracleError, match="registered authority"):
        invoke_oracle(oracle_candidate())


def test_instance_state_mutation_during_evaluate_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = RegisteredFakeAdapter(mutation="mutate_instance_state")
    register(monkeypatch, adapter)
    with pytest.raises(W3OracleError, match="identity/state changed during evaluation"):
        invoke_oracle(oracle_candidate())


@pytest.mark.parametrize("method_name", ["identity", "evaluate"])
def test_runtime_instance_method_override_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    adapter = RegisteredFakeAdapter()
    register(monkeypatch, adapter)
    monkeypatch.setattr(adapter, method_name, lambda *_args, **_kwargs: {})
    with pytest.raises(W3OracleError, match="cannot be overridden on the instance"):
        invoke_oracle(oracle_candidate())


def test_runtime_class_method_from_stdin_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = RegisteredFakeAdapter()
    register(monkeypatch, adapter)
    namespace: dict[str, object] = {}
    exec(compile("def injected(self, candidate): return {}", "<stdin>", "exec"), namespace)
    monkeypatch.setattr(RegisteredFakeAdapter, "evaluate", namespace["injected"])
    with pytest.raises(W3OracleError, match="no auditable source file|source file is unavailable"):
        invoke_oracle(oracle_candidate())


def test_runtime_code_object_swap_with_same_metadata_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CodeObjectAdapter(RegisteredFakeAdapter):
        def evaluate(self, candidate: dict) -> dict:
            return RegisteredFakeAdapter.evaluate(self, candidate)

    adapter = CodeObjectAdapter()
    register(monkeypatch, adapter)
    method = CodeObjectAdapter.evaluate
    original_code = method.__code__
    namespace: dict[str, object] = {}
    exec(
        compile("def replacement(self, candidate): return {}", original_code.co_filename, "exec"),
        namespace,
    )
    replacement = namespace["replacement"]
    assert inspect.isfunction(replacement)
    replacement_code = replacement.__code__.replace(
        co_filename=original_code.co_filename,
        co_name=original_code.co_name,
        co_qualname=original_code.co_qualname,
    )
    module_before = method.__module__
    qualname_before = method.__qualname__
    monkeypatch.setattr(method, "__code__", replacement_code)
    assert method.__module__ == module_before
    assert method.__qualname__ == qualname_before
    assert method.__code__.co_filename == original_code.co_filename
    with pytest.raises(W3OracleError, match="registered authority"):
        invoke_oracle(oracle_candidate())


@pytest.mark.parametrize("field", ["defaults", "kwdefaults"])
def test_runtime_defaults_or_kwdefaults_mutation_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    class DefaultsAdapter(RegisteredFakeAdapter):
        def evaluate(
            self,
            candidate: dict,
            marker: str = "registered",
            *,
            mode: str = "strict",
        ) -> dict:
            del marker, mode
            return RegisteredFakeAdapter.evaluate(self, candidate)

    adapter = DefaultsAdapter()
    register(monkeypatch, adapter)
    method = DefaultsAdapter.evaluate
    if field == "defaults":
        monkeypatch.setattr(method, "__defaults__", ("mutated",))
    else:
        monkeypatch.setattr(method, "__kwdefaults__", {"mode": "mutated"})
    with pytest.raises(W3OracleError, match="registered authority"):
        invoke_oracle(oracle_candidate())


def test_runtime_closure_mutation_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    closure_policy = "registered"

    class ClosureAdapter(RegisteredFakeAdapter):
        def evaluate(self, candidate: dict) -> dict:
            if closure_policy != "registered":
                raise AssertionError("mutated closure must never execute")
            return RegisteredFakeAdapter.evaluate(self, candidate)

    adapter = ClosureAdapter()
    register(monkeypatch, adapter)
    closure = ClosureAdapter.evaluate.__closure__
    assert closure is not None
    closure[0].cell_contents = "mutated"
    with pytest.raises(W3OracleError, match="registered authority"):
        invoke_oracle(oracle_candidate())


@pytest.mark.parametrize("extra_target", ["result", "predicates", "evidence"])
def test_extra_result_predicate_or_evidence_key_is_rejected(
    monkeypatch: pytest.MonkeyPatch, extra_target: str
) -> None:
    register(monkeypatch, RegisteredFakeAdapter(mutation=f"extra_{extra_target}"))
    with pytest.raises(W3OracleError, match="keys mismatch"):
        invoke_oracle(oracle_candidate())


def test_pending_missing_and_false_predicate_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutations = ["pending", "missing_semantic", "false_semantic"]
    for mutation in mutations:
        register(monkeypatch, RegisteredFakeAdapter(mutation=mutation))
        with pytest.raises(W3OracleError):
            invoke_oracle(oracle_candidate())


@pytest.mark.parametrize("family", ["F-1", "F-2"])
def test_contradictory_semantic_or_minimality_evidence_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
) -> None:
    mutation = "semantic_contradiction" if family == "F-1" else "minimality_contradiction"
    register(monkeypatch, RegisteredFakeAdapter(mutation=mutation))
    with pytest.raises(W3OracleError, match="contradicts|exact pass"):
        invoke_oracle(oracle_candidate(family))


def test_forged_binding_and_mismatched_f3_diagnostic_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register(monkeypatch, RegisteredFakeAdapter(mutation="forged_binding"))
    with pytest.raises(W3OracleError, match="binding candidate"):
        invoke_oracle(oracle_candidate())

    register(monkeypatch, RegisteredFakeAdapter(mutation="wrong_diagnostic"))
    with pytest.raises(W3OracleError, match="repair-bound"):
        invoke_oracle(oracle_candidate("F-3"))


def test_f3_diagnostic_must_explicitly_confirm_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register(monkeypatch, RegisteredFakeAdapter(mutation="diagnostic_not_repaired"))
    with pytest.raises(W3OracleError, match="exact repair pass"):
        invoke_oracle(oracle_candidate("F-3"))


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_receipt",
        "extra_receipt",
        "tampered_receipt_hash",
        "forged_receipt_candidate",
        "forged_receipt_pin",
    ],
)
def test_runtime_receipt_missing_extra_tamper_or_forgery_rejects(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    register(monkeypatch, RegisteredFakeAdapter(mutation=mutation))
    with pytest.raises(W3OracleError, match="keys mismatch|runtime receipt"):
        invoke_oracle(oracle_candidate())


def test_evidence_change_changes_bound_result_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    first = invoke_oracle(oracle_candidate())
    register(monkeypatch, RegisteredFakeAdapter(mutation="change_evidence"))
    second = invoke_oracle(oracle_candidate())
    assert first.oracle_result_sha256 != second.oracle_result_sha256
    assert first.semantic_result_sha256 != second.semantic_result_sha256
