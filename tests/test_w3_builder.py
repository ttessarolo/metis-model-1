from __future__ import annotations

import hashlib
import inspect
import marshal
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import metis_model1.w3_builder as builder_module
import metis_model1.w3_oracles as oracle_module
from metis_model1.dataset import build_split_manifest, load_schema
from metis_model1.provenance import canonical_json_bytes, example_id
from metis_model1.w3_builder import (
    PINNED_METIS_REVISION,
    W3BuildError,
    build_source_register,
    build_w3_dataset,
    validate_w3_run,
    validate_w3_source_register,
)
from metis_model1.w3_oracles import canonical_hash, required_predicates


def _identity(adapter: object) -> dict:
    adapter_type = type(adapter)
    source = inspect.getsourcefile(adapter_type)
    assert source is not None
    code_hash = "sha256:" + hashlib.sha256(Path(source).read_bytes()).hexdigest()
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
                f"{name}_method_source_file_sha256": (
                    "sha256:" + hashlib.sha256(Path(method_source).read_bytes()).hexdigest()
                ),
                f"{name}_method_code_sha256": code_sha,
                f"{name}_method_defaults_sha256": defaults_sha,
                f"{name}_method_kwdefaults_sha256": kwdefaults_sha,
                f"{name}_method_closure_sha256": closure_sha,
                f"{name}_method_callable_sha256": callable_sha,
            }
        )
    return {
        "schema_version": 1,
        "adapter_id": "registered-w3-test",
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
        "code_file_sha256": code_hash,
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


def benchmark(*roots: str) -> dict:
    body = {
        "schema_version": 1,
        "manifest_id": "frozen-benchmark-v1",
        "sealed": True,
        "benchmark_roots": list(roots) or [canonical_hash("benchmark-root")],
    }
    return {**body, "manifest_hash": canonical_hash(body)}


def _content(candidate: dict) -> dict:
    if candidate["family"] == "F-1":
        return {"request": candidate["request"], "target_source": candidate["target_source"]}
    if candidate["family"] == "F-2":
        key = "expected_delta" if "expected_delta" in candidate else "patch"
        return {
            "before_source": candidate["before_source"],
            "after_source": candidate["after_source"],
            key: candidate[key],
        }
    return {
        "mutated_source": candidate["mutated_source"],
        "expected_diagnostic": candidate["expected_diagnostic"],
        "fixed_source": candidate["fixed_source"],
        "mutation_spec": candidate["mutation_spec"],
    }


def _rebind_content(row: dict) -> None:
    content_sha = canonical_hash(_content(row))
    row["root_evidence"]["content_sha256"] = content_sha
    row["rights"]["attestation"]["content_sha256"] = content_sha


def _rehash_run(run: dict) -> None:
    examples = []
    for record in run["accepted_records"]:
        row = record["dataset_example"]
        row["example_id"] = example_id(1, row["input"], row["output"])
        record["text_sha256"] = canonical_hash({"input": row["input"], "output": row["output"]})
        examples.append(row)
    run["split_manifest_id"] = build_split_manifest(examples)["split_manifest_id"]
    body = {key: value for key, value in run.items() if key != "manifest_sha256"}
    run["manifest_sha256"] = canonical_hash(body)


def _rehash_manifest(run: dict) -> None:
    body = {key: value for key, value in run.items() if key != "manifest_sha256"}
    run["manifest_sha256"] = canonical_hash(body)


def candidate(
    index: int,
    family: str,
    *,
    split: str = "train",
    parents: list[str] | None = None,
    ancestor_roots: list[str] | None = None,
) -> dict:
    common = {
        "candidate_id": f"candidate-{index}",
        "family": family,
        "split": split,
        "semantic_spec": {"intent": family, "fixture": index},
        "parents": [] if parents is None else parents,
    }
    if family == "F-1":
        common.update(
            request=f"Author property {index}",
            target_source=f'property p{index} {{ value: "v{index}" }}',
        )
    elif family == "F-2":
        common.update(
            before_source=f'property p{index} {{ value: "before{index}" }}',
            after_source=f'property p{index} {{ value: "after{index}" }}',
            expected_delta={"replace": [f"before{index}", f"after{index}"]},
        )
    else:
        common.update(
            mutated_source=f"property p{index} {{ value: }}",
            expected_diagnostic={"code": f"missing-value-{index}"},
            fixed_source=f'property p{index} {{ value: "fixed{index}" }}',
            mutation_spec={"removed": f"fixed{index}"},
        )
    content_sha = canonical_hash(_content(common))
    semantic_sha = canonical_hash(common["semantic_spec"])
    evidence = {"origin": "test-fixture", "index": index}
    common["root_evidence"] = {
        "content_sha256": content_sha,
        "semantic_spec_sha256": semantic_sha,
        "template_root": canonical_hash(["template", index]),
        "generator_root": canonical_hash(["generator", index]),
        "session_root": canonical_hash(["session", index]),
        "ancestor_roots": [] if ancestor_roots is None else ancestor_roots,
    }
    common["rights"] = {
        "license_id": "CC0-1.0",
        "policy": "public_synthetic_permitted",
        "scope": "local_training_and_evaluation",
        "attestation": {
            "content_sha256": content_sha,
            "evidence": evidence,
            "evidence_sha256": canonical_hash(evidence),
            "reviewer": "independent-test-reviewer",
        },
    }
    return common


class RegisteredAdapter:
    def __init__(
        self,
        *,
        reject_id: str | None = None,
        forced_ast: str | None = None,
        evidence_tag: str = "default",
    ) -> None:
        self.reject_id = reject_id
        self.forced_ast = forced_ast
        self.evidence_tag = evidence_tag

    def identity(self) -> dict:
        return _identity(self)

    def evaluate(self, item: dict) -> dict:
        candidate_sha = canonical_hash(item)
        identity_sha = canonical_hash(self.identity())
        names = required_predicates(item["family"])
        evidence = {
            name: {"candidate_sha256": candidate_sha, "details": {"name": name}}
            for name in ("parse", "link", "validate", "compile")
        }
        evidence["semantic"] = {
            "candidate_sha256": candidate_sha,
            "semantic_spec_sha256": item["semantic_spec_sha256"],
            "details": {"matched": True, "tag": self.evidence_tag},
        }
        if item["family"] == "F-2":
            key = "expected_delta" if "expected_delta" in item else "patch"
            evidence["patch_minimality"] = {
                "candidate_sha256": candidate_sha,
                "before_sha256": canonical_hash(item["before_source"]),
                "after_sha256": canonical_hash(item["after_source"]),
                "delta_sha256": canonical_hash(item[key]),
                "details": {"minimal": True},
            }
        if item["family"] == "F-3":
            evidence["diagnostic"] = {
                "candidate_sha256": candidate_sha,
                "mutated_sha256": canonical_hash(item["mutated_source"]),
                "fixed_sha256": canonical_hash(item["fixed_source"]),
                "expected_diagnostic_sha256": canonical_hash(item["expected_diagnostic"]),
                "mutation_spec_sha256": canonical_hash(item["mutation_spec"]),
                "details": {"repaired": True},
            }
        evidence["ast"] = {
            "signature": self.forced_ast or canonical_hash(["ast", candidate_sha]),
            "evidence": {"candidate_sha256": candidate_sha},
        }
        evidence["ir"] = {
            "signature": canonical_hash(["ir", candidate_sha]),
            "evidence": {"candidate_sha256": candidate_sha},
        }
        evidence["binding"] = {
            "candidate_sha256": candidate_sha,
            "content_sha256": item["content_sha256"],
            "semantic_spec_sha256": item["semantic_spec_sha256"],
        }
        return {
            "schema_version": 1,
            "status": "fail" if item["candidate_id"] == self.reject_id else "pass",
            "family": item["family"],
            "candidate_sha256": candidate_sha,
            "adapter_identity_sha256": identity_sha,
            "runtime_receipt": _runtime_receipt(candidate_sha, identity_sha),
            "predicates": {name: True for name in names},
            "evidence": evidence,
        }


def authorise(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict],
    frozen: dict | None = None,
    adapter: RegisteredAdapter | None = None,
) -> tuple[dict, dict]:
    frozen = benchmark() if frozen is None else frozen
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256", frozen["manifest_hash"]
    )
    register = build_source_register(rows, benchmark_manifest=frozen)
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_SOURCE_REGISTER_SHA256", register["manifest_sha256"]
    )
    adapter = RegisteredAdapter() if adapter is None else adapter
    monkeypatch.setattr(oracle_module, "REGISTERED_W3_ORACLE_ADAPTER", adapter)
    monkeypatch.setattr(
        oracle_module,
        "REGISTERED_W3_ORACLE_IDENTITY_SHA256",
        canonical_hash(adapter.identity()),
    )
    return frozen, register


def test_schemas_are_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(load_schema("w3-source-register.schema.json"))
    Draft202012Validator.check_schema(load_schema("w3-run.schema.json"))


def test_public_build_and_replay_have_no_caller_oracle_or_example_sidecar() -> None:
    build_parameters = inspect.signature(build_w3_dataset).parameters
    replay_parameters = inspect.signature(validate_w3_run).parameters
    assert set(build_parameters) == {"candidates", "benchmark_manifest"}
    assert set(replay_parameters) == {
        "run_manifest",
        "source_register",
        "benchmark_manifest",
    }
    assert "adapter" not in build_parameters
    assert "adapter" not in replay_parameters
    assert "examples" not in replay_parameters


def test_f1_f2_f3_positive_exact_counts_and_pinned_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [candidate(1, "F-1"), candidate(2, "F-2"), candidate(3, "F-3")]
    frozen, register = authorise(monkeypatch, rows)
    result = build_w3_dataset(rows, benchmark_manifest=frozen)
    assert result.source_register == register
    assert result.run_manifest["counts"] == {
        "in": 3,
        "out": 3,
        "distinct": 3,
        "rejected": 0,
        "gaps": 0,
    }
    assert result.run_manifest["claim"] == "no_accuracy_claim"
    assert {row["metis"]["source_revision"] for row in result.examples} == {PINNED_METIS_REVISION}
    assert {row["task_family"] for row in result.examples} == {"F-1", "F-2", "F-3"}
    assert validate_w3_source_register(register, candidates=rows, benchmark_manifest=frozen) == []
    assert (
        validate_w3_run(
            result.run_manifest,
            source_register=register,
            benchmark_manifest=frozen,
        )
        == []
    )


def test_f2_f3_user_messages_carry_the_complete_training_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [candidate(2, "F-2"), candidate(3, "F-3")]
    frozen, _ = authorise(monkeypatch, rows)
    result = build_w3_dataset(rows, benchmark_manifest=frozen)
    for row in result.examples:
        user_message = row["messages"][1]["content"]
        serialized = user_message.split("W3_INPUT_JSON=", maxsplit=1)[1]
        assert serialized == canonical_json_bytes(row["input"]).decode()
        assert all(
            canonical_json_bytes(value).decode() in serialized for value in row["input"].values()
        )
    f2 = next(row for row in result.examples if row["task_family"] == "F-2")
    f3 = next(row for row in result.examples if row["task_family"] == "F-3")
    assert set(f2["input"]) == {"before_source", "expected_delta"}
    assert set(f3["input"]) == {
        "mutated_source",
        "expected_diagnostic",
        "mutation_spec",
    }


@pytest.mark.parametrize(
    ("family", "before_field", "after_field"),
    [
        ("F-2", "before_source", "after_source"),
        ("F-3", "mutated_source", "fixed_source"),
    ],
)
def test_edit_and_repair_must_change_source(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    before_field: str,
    after_field: str,
) -> None:
    row = candidate(1, family)
    row[after_field] = row[before_field]
    _rebind_content(row)
    frozen = benchmark()
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256", frozen["manifest_hash"]
    )
    with pytest.raises(W3BuildError, match="must differ"):
        build_source_register([row], benchmark_manifest=frozen)


def test_unset_and_self_certified_authorities_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    row = candidate(1, "F-1")
    frozen = benchmark()
    with pytest.raises(W3BuildError, match="benchmark authority is unset"):
        build_source_register([row], benchmark_manifest=frozen)
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256", frozen["manifest_hash"]
    )
    build_source_register([row], benchmark_manifest=frozen)
    with pytest.raises(W3BuildError, match="source-register authority is unset"):
        build_w3_dataset([row], benchmark_manifest=frozen)


@pytest.mark.parametrize("family", ["F-2", "F-3"])
def test_structureless_family_candidate_fails(monkeypatch: pytest.MonkeyPatch, family: str) -> None:
    row = candidate(1, family)
    if family == "F-2":
        row.pop("expected_delta")
    else:
        row.pop("expected_diagnostic")
    frozen = benchmark()
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256", frozen["manifest_hash"]
    )
    with pytest.raises(W3BuildError, match=family):
        build_source_register([row], benchmark_manifest=frozen)


def test_parent_child_implicitly_share_component(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = candidate(1, "F-1")
    child = candidate(2, "F-1", parents=[parent["candidate_id"]])
    frozen, register = authorise(monkeypatch, [child, parent])
    groups = {source["leakage_group"] for source in register["sources"]}
    assert len(groups) == 1
    result = build_w3_dataset([parent, child], benchmark_manifest=frozen)
    assert {row["provenance"]["leakage_group"] for row in result.examples} == groups


def test_shared_ancestor_or_sibling_parent_cross_split_is_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = benchmark()
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256", frozen["manifest_hash"]
    )
    shared = canonical_hash("shared-ancestor")
    left = candidate(1, "F-1", split="train", ancestor_roots=[shared])
    right = candidate(2, "F-1", split="dev", ancestor_roots=[shared])
    with pytest.raises(W3BuildError, match="component crosses split"):
        build_source_register([left, right], benchmark_manifest=frozen)

    sibling_left = candidate(3, "F-1", split="train", parents=[shared])
    sibling_right = candidate(4, "F-1", split="dev", parents=[shared])
    with pytest.raises(W3BuildError, match="component crosses split"):
        build_source_register([sibling_left, sibling_right], benchmark_manifest=frozen)


def test_benchmark_copy_fake_manifest_and_frozen_split_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = candidate(1, "F-1")
    content_root = row["root_evidence"]["content_sha256"]
    frozen = benchmark(content_root)
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256", frozen["manifest_hash"]
    )
    with pytest.raises(W3BuildError, match="benchmark ancestry"):
        build_source_register([row], benchmark_manifest=frozen)

    fake = benchmark(canonical_hash("fake"))
    with pytest.raises(W3BuildError, match="registered authority"):
        build_source_register([row], benchmark_manifest=fake)

    frozen_row = candidate(2, "F-1", split="frozen")
    with pytest.raises(W3BuildError, match="W3 split"):
        build_source_register([frozen_row], benchmark_manifest=frozen)


@pytest.mark.parametrize(
    ("family", "frozen_output_field"),
    [
        ("F-1", "target_source"),
        ("F-2", "after_source"),
        ("F-3", "fixed_source"),
    ],
)
def test_atomic_frozen_output_copy_is_rejected_for_every_family(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    frozen_output_field: str,
) -> None:
    row = candidate(7, family)
    # Other family inputs are independently authored/paraphrased; the copied
    # output alone must still intersect the registered W1 benchmark roots.
    frozen = benchmark(canonical_hash(row[frozen_output_field]))
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256", frozen["manifest_hash"]
    )
    with pytest.raises(W3BuildError, match="benchmark ancestry"):
        build_source_register([row], benchmark_manifest=frozen)


def test_proprietary_rights_and_content_attestation_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = benchmark()
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256", frozen["manifest_hash"]
    )
    proprietary = candidate(1, "F-1")
    proprietary["rights"]["license_id"] = "PROPRIETARY"
    with pytest.raises(W3BuildError, match="license"):
        build_source_register([proprietary], benchmark_manifest=frozen)
    unbound = candidate(2, "F-1")
    unbound["rights"]["attestation"]["content_sha256"] = canonical_hash("other")
    with pytest.raises(W3BuildError, match="not bound"):
        build_source_register([unbound], benchmark_manifest=frozen)


def test_register_tamper_even_with_rehash_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [candidate(1, "F-1")]
    frozen, register = authorise(monkeypatch, rows)
    tampered = deepcopy(register)
    tampered["sources"][0]["rights"]["attestation"]["reviewer"] = "forged-reviewer"
    source = tampered["sources"][0]
    source_body = {key: value for key, value in source.items() if key != "source_record_sha256"}
    source["source_record_sha256"] = canonical_hash(source_body)
    body = {key: value for key, value in tampered.items() if key != "manifest_sha256"}
    tampered["manifest_sha256"] = canonical_hash(body)
    assert validate_w3_source_register(tampered, candidates=rows, benchmark_manifest=frozen)


def test_duplicate_ids_cycles_malformed_and_order_determinism(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = benchmark()
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256", frozen["manifest_hash"]
    )
    duplicate = [candidate(1, "F-1"), candidate(1, "F-1")]
    with pytest.raises(W3BuildError, match="duplicate candidate_id"):
        build_source_register(duplicate, benchmark_manifest=frozen)
    left = candidate(1, "F-1", parents=["candidate-2"])
    right = candidate(2, "F-1", parents=["candidate-1"])
    with pytest.raises(W3BuildError, match="cycle"):
        build_source_register([left, right], benchmark_manifest=frozen)
    with pytest.raises(W3BuildError, match="candidate must be an object"):
        build_source_register(["bad"], benchmark_manifest=frozen)  # type: ignore[list-item]
    with pytest.raises(W3BuildError, match="source register must be an object"):
        validate_w3_source_register(  # type: ignore[arg-type]
            "bad", candidates=[candidate(9, "F-1")], benchmark_manifest=frozen
        )
    with pytest.raises(W3BuildError, match="run manifest must be an object"):
        validate_w3_run(  # type: ignore[arg-type]
            "bad",
            source_register={},
            benchmark_manifest=frozen,
        )

    rows = [candidate(3, "F-3"), candidate(1, "F-1"), candidate(2, "F-2")]
    first = build_source_register(rows, benchmark_manifest=frozen)
    second = build_source_register(list(reversed(rows)), benchmark_manifest=frozen)
    assert first == second


def test_none_iterables_and_unsafe_candidate_ids_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = benchmark()
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256", frozen["manifest_hash"]
    )
    with pytest.raises(W3BuildError, match="candidates must be an iterable"):
        build_source_register(None, benchmark_manifest=frozen)  # type: ignore[arg-type]
    with pytest.raises(W3BuildError, match="candidates must be an iterable"):
        build_w3_dataset(None, benchmark_manifest=frozen)  # type: ignore[arg-type]
    register = build_source_register([candidate(9, "F-1")], benchmark_manifest=frozen)
    with pytest.raises(W3BuildError, match="candidates must be an iterable"):
        validate_w3_source_register(  # type: ignore[arg-type]
            register,
            candidates=None,
            benchmark_manifest=frozen,
        )

    for unsafe_id in ("../escape", "nested/path", "/absolute", ".."):
        row = candidate(1, "F-1")
        row["candidate_id"] = unsafe_id
        with pytest.raises(W3BuildError, match="safe metadata identifier"):
            build_source_register([row], benchmark_manifest=frozen)


@pytest.mark.parametrize(
    "bad_split",
    [
        pytest.param({}, id="mapping"),
        pytest.param([], id="list"),
        pytest.param(1, id="integer"),
        pytest.param(None, id="null"),
    ],
)
def test_malformed_split_scalar_always_raises_w3_build_error(
    monkeypatch: pytest.MonkeyPatch,
    bad_split: object,
) -> None:
    frozen = benchmark()
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256", frozen["manifest_hash"]
    )
    row = candidate(1, "F-1")
    row["split"] = bad_split
    with pytest.raises(W3BuildError, match="W3 split"):
        build_source_register([row], benchmark_manifest=frozen)


@pytest.mark.parametrize(
    "bad_license",
    [
        pytest.param({}, id="mapping"),
        pytest.param([], id="list"),
        pytest.param(1, id="integer"),
        pytest.param(None, id="null"),
    ],
)
def test_malformed_license_scalar_always_raises_w3_build_error(
    monkeypatch: pytest.MonkeyPatch,
    bad_license: object,
) -> None:
    frozen = benchmark()
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256", frozen["manifest_hash"]
    )
    row = candidate(1, "F-1")
    row["rights"]["license_id"] = bad_license
    with pytest.raises(W3BuildError, match="rights license"):
        build_source_register([row], benchmark_manifest=frozen)


@pytest.mark.parametrize(
    ("target", "bad_value", "message"),
    [
        ("family", {}, "family"),
        ("parents", [{}], "parents"),
        ("template_root", {}, "template/generator/session"),
        ("rights_policy", {}, "policy/scope"),
        ("semantic_spec", "hash-only", "semantic_spec"),
        ("expected_delta", 7, "expected_delta"),
    ],
)
def test_nearby_nested_type_edges_fail_as_w3_build_errors(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    bad_value: object,
    message: str,
) -> None:
    frozen = benchmark()
    monkeypatch.setattr(
        builder_module, "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256", frozen["manifest_hash"]
    )
    row = candidate(1, "F-2" if target == "expected_delta" else "F-1")
    if target == "template_root":
        row["root_evidence"]["template_root"] = bad_value
    elif target == "rights_policy":
        row["rights"]["policy"] = bad_value
    else:
        row[target] = bad_value
    with pytest.raises(W3BuildError, match=message):
        build_source_register([row], benchmark_manifest=frozen)


def test_rejected_roster_and_ast_cross_split_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [candidate(1, "F-1"), candidate(2, "F-1")]
    frozen, _ = authorise(monkeypatch, rows, adapter=RegisteredAdapter(reject_id="candidate-2"))
    result = build_w3_dataset(rows, benchmark_manifest=frozen)
    assert result.run_manifest["counts"] == {
        "in": 2,
        "out": 1,
        "distinct": 1,
        "rejected": 1,
        "gaps": 1,
    }
    assert result.rejected[0]["candidate_id"] == "candidate-2"

    cross = [candidate(3, "F-1", split="train"), candidate(4, "F-1", split="dev")]
    frozen, _ = authorise(
        monkeypatch,
        cross,
        adapter=RegisteredAdapter(forced_ast=canonical_hash("same-ast")),
    )
    with pytest.raises(W3BuildError, match="ast duplicate crosses split"):
        build_w3_dataset(cross, benchmark_manifest=frozen)


def test_oracle_structural_match_to_benchmark_is_run_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen_ast = canonical_hash("frozen-ast-signature")

    class SelectiveBenchmarkCopyAdapter(RegisteredAdapter):
        def evaluate(self, item: dict) -> dict:
            result = RegisteredAdapter.evaluate(self, item)
            if item["candidate_id"] == "candidate-1":
                result["evidence"]["ast"]["signature"] = frozen_ast
            return result

    rows = [candidate(1, "F-1"), candidate(2, "F-1")]
    frozen = benchmark(frozen_ast)
    authorise(monkeypatch, rows, frozen, adapter=SelectiveBenchmarkCopyAdapter())
    with pytest.raises(W3BuildError, match="AST/IR signature"):
        build_w3_dataset(rows, benchmark_manifest=frozen)


def test_run_evidence_tamper_and_rehash_still_breaks_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [candidate(1, "F-1")]
    frozen, register = authorise(monkeypatch, rows)
    result = build_w3_dataset(rows, benchmark_manifest=frozen)
    tampered = deepcopy(result.run_manifest)
    tampered["accepted_records"][0]["oracle_evidence"]["evidence"]["semantic"]["details"] = {
        "matched": False
    }
    _rehash_manifest(tampered)
    errors = validate_w3_run(
        tampered,
        source_register=register,
        benchmark_manifest=frozen,
    )
    assert any("deterministic register/benchmark/Oracle replay" in error for error in errors)


@pytest.mark.parametrize("attack", ["output", "split", "source_revision"])
def test_run_replay_rejects_self_consistent_forged_dataset_rows(
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    rows = [candidate(1, "F-1")]
    frozen, register = authorise(monkeypatch, rows)
    result = build_w3_dataset(rows, benchmark_manifest=frozen)
    tampered = deepcopy(result.run_manifest)
    row = tampered["accepted_records"][0]["dataset_example"]
    if attack == "output":
        forged = 'property forged { value: "forged" }'
        row["output"] = {"assistant_content": forged, "source": forged}
        row["messages"][2]["content"] = forged
    elif attack == "split":
        row["split"] = "dev"
    else:
        row["metis"]["source_revision"] = "0" * 40
    _rehash_run(tampered)
    errors = validate_w3_run(
        tampered,
        source_register=register,
        benchmark_manifest=frozen,
    )
    assert any("deterministic register/benchmark/Oracle replay" in error for error in errors)


@pytest.mark.parametrize("attack", ["empty_example", "empty_oracle_evidence"])
def test_malformed_embedded_records_return_validation_errors_not_key_errors(
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    rows = [candidate(1, "F-1")]
    frozen, register = authorise(monkeypatch, rows)
    result = build_w3_dataset(rows, benchmark_manifest=frozen)
    tampered = deepcopy(result.run_manifest)
    record = tampered["accepted_records"][0]
    if attack == "empty_example":
        record["dataset_example"] = {}
    else:
        record["oracle_evidence"]["evidence"] = {}
    _rehash_manifest(tampered)
    errors = validate_w3_run(
        tampered,
        source_register=register,
        benchmark_manifest=frozen,
    )
    assert errors


def test_rejected_reason_and_duplicate_roster_are_bound_by_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [candidate(1, "F-1"), candidate(2, "F-1")]
    adapter = RegisteredAdapter(reject_id="candidate-2")
    frozen, register = authorise(monkeypatch, rows, adapter=adapter)
    result = build_w3_dataset(rows, benchmark_manifest=frozen)

    forged_reason = deepcopy(result.run_manifest)
    forged_reason["rejected"][0]["reason"] = "caller says rejected"
    _rehash_manifest(forged_reason)
    assert validate_w3_run(
        forged_reason,
        source_register=register,
        benchmark_manifest=frozen,
    )

    duplicated = deepcopy(result.run_manifest)
    duplicated["rejected"].append(deepcopy(duplicated["rejected"][0]))
    duplicated["counts"]["rejected"] += 1
    duplicated["counts"]["gaps"] += 1
    _rehash_manifest(duplicated)
    assert validate_w3_run(
        duplicated,
        source_register=register,
        benchmark_manifest=frozen,
    )


def test_independent_evidence_change_changes_bound_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [candidate(1, "F-1")]
    frozen, _ = authorise(monkeypatch, rows, adapter=RegisteredAdapter(evidence_tag="first"))
    first = build_w3_dataset(rows, benchmark_manifest=frozen)
    authorise(monkeypatch, rows, frozen, adapter=RegisteredAdapter(evidence_tag="second"))
    second = build_w3_dataset(rows, benchmark_manifest=frozen)
    assert first.run_manifest["manifest_sha256"] != second.run_manifest["manifest_sha256"]
    assert (
        first.run_manifest["accepted_records"][0]["oracle_result_sha256"]
        != second.run_manifest["accepted_records"][0]["oracle_result_sha256"]
    )
