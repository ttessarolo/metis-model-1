from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import metis_model1.w3_builder as builder_module
import metis_model1.w3_oracles as oracle_module
import metis_model1.w3_production_adapter as production_module
from metis_model1.provenance import canonical_json_bytes
from metis_model1.w3_builder import W3BuildError, build_source_register, build_w3_dataset
from metis_model1.w3_oracles import canonical_hash
from metis_model1.w3_production_adapter import ProductionW3Adapter

PROJECT_ROOT = Path(__file__).parents[1]
METIS_ROOT = Path("/Users/tommasotessarolo/Developer/ares-matioska/metis")
CANDIDATES_PATH = PROJECT_ROOT / "manifests/w3-f1-f3-smoke-candidates.json"
REGISTRY_PATH = PROJECT_ROOT / "manifests/w3-f1-f3-smoke-semantic-specs.json"
SEMANTIC_SCHEMA_PATH = PROJECT_ROOT / "schemas/w3-semantic-spec.schema.json"
W3_RUN_SCHEMA_PATH = PROJECT_ROOT / "schemas/w3-run.schema.json"


def _manifest_hash(value: dict) -> str:
    return canonical_hash({key: item for key, item in value.items() if key != "manifest_sha256"})


def _benchmark() -> dict:
    body = {
        "schema_version": 1,
        "manifest_id": "w3-bridge-unrelated-frozen-benchmark-v1",
        "sealed": True,
        "benchmark_roots": [canonical_hash("unrelated-frozen-benchmark-root")],
    }
    return {**body, "manifest_hash": canonical_hash(body)}


def _load_manifests() -> tuple[dict, dict]:
    return (
        json.loads(CANDIDATES_PATH.read_text(encoding="utf-8")),
        json.loads(REGISTRY_PATH.read_text(encoding="utf-8")),
    )


def _git_bytes(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(METIS_ROOT), *args])


def _project_git_bytes(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(PROJECT_ROOT), *args])


def _rehash_forged_receipt(receipt: dict) -> None:
    for execution in receipt.get("executions", []):
        envelope = execution["envelope"]
        evidence = envelope["evidence"]
        result = envelope["result"]
        evidence["input_sha256"] = canonical_hash(execution["request"])
        evidence["diagnostics_sha256"] = canonical_hash(result["diagnostics"])
        evidence["ast_sha256"] = canonical_hash(result["ast"]["inventory"])
        evidence["ir_sha256"] = (
            None if result["ir"]["value"] is None else canonical_hash(result["ir"]["value"])
        )
        evidence["runtime_sha256"] = canonical_hash(evidence["runtime_identity"])
        evidence["metis_status_sha256"] = canonical_hash(evidence["metis_status"])
        evidence.pop("envelope_sha256", None)
        evidence["envelope_sha256"] = canonical_hash(envelope)
        execution["result_sha256"] = canonical_hash(result)
        execution["diagnostics_sha256"] = evidence["diagnostics_sha256"]
        execution["ast_sha256"] = evidence["ast_sha256"]
        execution["ir_sha256"] = evidence["ir_sha256"]
        execution["runtime_sha256"] = evidence["runtime_sha256"]
        execution["runtime_identity"] = evidence["runtime_identity"]
        execution["metis_status_sha256"] = evidence["metis_status_sha256"]
        artifact = PROJECT_ROOT / execution["artifact_path"]
        if artifact.is_file():
            execution["artifact_sha256"] = (
                "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
            )
        body = {key: value for key, value in execution.items() if key != "receipt_sha256"}
        execution["receipt_sha256"] = canonical_hash(body)
    body = {key: value for key, value in receipt.items() if key != "runtime_receipt_sha256"}
    receipt["runtime_receipt_sha256"] = canonical_hash(body)


def _run_real_gate() -> dict:
    candidates_manifest, registry = _load_manifests()
    benchmark = _benchmark()
    before_head = _git_bytes("rev-parse", "HEAD").strip().decode()
    before_status = _git_bytes("status", "--porcelain=v1", "-z", "--untracked-files=all")
    project_before_head = _project_git_bytes("rev-parse", "HEAD").strip().decode()
    project_before_status = _project_git_bytes(
        "status", "--porcelain=v1", "-z", "--untracked-files=all"
    )
    builder_module.REGISTERED_W3_BENCHMARK_MANIFEST_SHA256 = benchmark["manifest_hash"]
    register = build_source_register(
        candidates_manifest["candidates"], benchmark_manifest=benchmark
    )
    builder_module.REGISTERED_W3_SOURCE_REGISTER_SHA256 = register["manifest_sha256"]
    production_module.REGISTERED_W3_SEMANTIC_REGISTRY_SHA256 = registry["manifest_sha256"]
    adapter = ProductionW3Adapter(
        semantic_registry_json=REGISTRY_PATH.read_text(encoding="utf-8"),
        metis_root=str(METIS_ROOT),
    )
    oracle_module.REGISTERED_W3_ORACLE_ADAPTER = adapter
    oracle_module.REGISTERED_W3_ORACLE_IDENTITY_SHA256 = canonical_hash(adapter.identity())
    result = build_w3_dataset(candidates_manifest["candidates"], benchmark_manifest=benchmark)
    after_head = _git_bytes("rev-parse", "HEAD").strip().decode()
    after_status = _git_bytes("status", "--porcelain=v1", "-z", "--untracked-files=all")
    executions = [
        execution
        for record in result.run_manifest["accepted_records"]
        for execution in record["oracle_evidence"]["runtime_receipt"]["executions"]
    ]
    first_record = result.run_manifest["accepted_records"][0]
    first_receipt = first_record["oracle_evidence"]["runtime_receipt"]
    mutation_attacks = 0
    for attack in range(13):
        forged = deepcopy(first_receipt)
        if attack == 0:
            forged["executions"] = []
        elif attack == 1:
            forged["executions"][0]["role"] = "after"
        elif attack == 2:
            forged["executions"][0]["source_sha256"] = canonical_hash("forged")
        elif attack == 3:
            forged["executions"][0]["request"]["filename"] = "bridge/forged.metis"
        elif attack == 4:
            forged["executions"][0]["request"]["endpoint"] = "play.forged"
        elif attack == 5:
            forged["executions"][0]["request"]["workspace_sources"] = [
                {"filename": "forged.metis", "source": "metis 0.43\n"}
            ]
        elif attack == 6:
            forged["executions"][0]["request"]["extra"] = True
        elif attack == 7:
            forged["executions"][0]["envelope"]["result"]["status"] = "invalid"
        elif attack == 8:
            other = executions[1]
            forged["executions"][0]["artifact_path"] = other["artifact_path"]
            forged["executions"][0]["artifact_sha256"] = other["artifact_sha256"]
        elif attack == 9:
            forged["executions"][0]["artifact_path"] = "../escape.json"
        elif attack == 10:
            forged["semantic_registry_sha256"] = canonical_hash("forged")
        elif attack == 11:
            forged["receipt_mode"] = "fixture-policy"
        else:
            forged["schema_version"] = 1
        _rehash_forged_receipt(forged)
        try:
            oracle_module._validate_runtime_receipt(
                forged,
                first_record["candidate_sha256"],
                first_record["oracle_evidence"]["adapter_identity_sha256"],
                candidate=first_record["candidate"],
                require_real=True,
                expected_registry_sha256=first_receipt["semantic_registry_sha256"],
            )
        except oracle_module.W3OracleError:
            mutation_attacks += 1
    run_bytes = canonical_json_bytes(result.run_manifest)
    project_after_head = _project_git_bytes("rev-parse", "HEAD").strip().decode()
    project_after_status = _project_git_bytes(
        "status", "--porcelain=v1", "-z", "--untracked-files=all"
    )
    return {
        "candidate_counts": candidates_manifest["counts"],
        "run_counts": result.run_manifest["counts"],
        "roles": [execution["role"] for execution in executions],
        "statuses": [execution["envelope"]["result"]["status"] for execution in executions],
        "failure_kinds": [
            None
            if execution["envelope"]["result"]["failure"] is None
            else execution["envelope"]["result"]["failure"]["kind"]
            for execution in executions
        ],
        "receipt_hashes": [execution["receipt_sha256"] for execution in executions],
        "artifact_hashes": [
            hashlib.sha256((PROJECT_ROOT / execution["artifact_path"]).read_bytes()).hexdigest()
            for execution in executions
        ],
        "run_bytes_sha256": hashlib.sha256(run_bytes).hexdigest(),
        "run_bytes_length": len(run_bytes),
        "run_manifest_sha256": result.run_manifest["manifest_sha256"],
        "metis_head": before_head,
        "metis_status_sha256": hashlib.sha256(before_status).hexdigest(),
        "metis_invariant": before_head == after_head and before_status == after_status,
        "project_invariant": (
            project_before_head == project_after_head
            and project_before_status == project_after_status
        ),
        "mutation_attacks_closed": mutation_attacks,
    }


def test_production_authorities_ship_unset() -> None:
    assert production_module.REGISTERED_W3_SEMANTIC_REGISTRY_SHA256 is None


@pytest.mark.parametrize("operation", ["identity", "evaluate"])
def test_l66_legacy_production_adapter_stops_before_registry_artifact_or_runner(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    observed: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        observed.append("forbidden-boundary")
        raise AssertionError("legacy adapter crossed the protected-broker STOP")

    monkeypatch.setattr(production_module, "_registered_registry", forbidden)
    monkeypatch.setattr(production_module, "_safe_artifact_namespace", forbidden)
    monkeypatch.setattr(production_module, "run_oracle", forbidden)
    adapter = ProductionW3Adapter(
        semantic_registry_json="{}",
        metis_root="/absent-metis",
    )
    with pytest.raises(oracle_module.W3OracleTrustError, match="protected execution broker"):
        if operation == "identity":
            adapter.identity()
        else:
            adapter.evaluate({})
    assert observed == []
    assert oracle_module.REGISTERED_W3_ORACLE_ADAPTER is None
    assert oracle_module.REGISTERED_W3_ORACLE_IDENTITY_SHA256 is None


def test_smoke_manifests_are_exact_typed_and_conservatively_one_grouped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates_manifest, registry = _load_manifests()
    assert candidates_manifest["manifest_sha256"] == _manifest_hash(candidates_manifest)
    assert registry["manifest_sha256"] == _manifest_hash(registry)
    schema = json.loads(SEMANTIC_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(registry)) == []
    assert [spec["family"] for spec in registry["specs"]] == ["F-1", "F-2", "F-3"]
    assert all(
        spec["spec_sha256"]
        == canonical_hash({key: item for key, item in spec.items() if key != "spec_sha256"})
        for spec in registry["specs"]
    )
    benchmark = _benchmark()
    monkeypatch.setattr(
        builder_module,
        "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256",
        benchmark["manifest_hash"],
    )
    register = build_source_register(
        candidates_manifest["candidates"], benchmark_manifest=benchmark
    )
    assert register["counts"] == {"in": 3, "out": 3, "distinct": 3, "gaps": 0}
    assert len({source["leakage_group"] for source in register["sources"]}) == 1
    assert (
        len(
            {
                candidate["root_evidence"]["session_root"]
                for candidate in candidates_manifest["candidates"]
            }
        )
        == 1
    )
    assert (
        len(
            {
                candidate["root_evidence"]["generator_root"]
                for candidate in candidates_manifest["candidates"]
            }
        )
        == 1
    )


def test_legacy_production_identity_stops_before_registry_or_transitive_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, registry = _load_manifests()
    adapter = ProductionW3Adapter(
        semantic_registry_json=REGISTRY_PATH.read_text(encoding="utf-8"),
        metis_root=str(METIS_ROOT),
    )
    for authority in (None, registry["manifest_sha256"]):
        monkeypatch.setattr(
            production_module,
            "REGISTERED_W3_SEMANTIC_REGISTRY_SHA256",
            authority,
        )
        with pytest.raises(oracle_module.W3OracleTrustError, match="protected execution broker"):
            adapter.identity()


@pytest.mark.parametrize("dependency", ["run_oracle", "verify_oracle_envelope"])
def test_legacy_production_identity_never_reaches_executor_or_verifier_globals(
    monkeypatch: pytest.MonkeyPatch,
    dependency: str,
) -> None:
    observed: list[str] = []
    adapter = ProductionW3Adapter(
        semantic_registry_json="{}",
        metis_root="/definitely/not/metis",
    )

    def replacement(*args: object, **kwargs: object) -> dict:
        del args, kwargs
        observed.append(dependency)
        return {"forged": True}

    monkeypatch.setattr(production_module, dependency, replacement)
    with pytest.raises(oracle_module.W3OracleTrustError, match="protected execution broker"):
        adapter.identity()
    assert observed == []


def test_legacy_production_identity_does_not_measure_executor_live_globals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []
    adapter = ProductionW3Adapter(
        semantic_registry_json="{}",
        metis_root="/definitely/not/metis",
    )

    def forbidden(*args: object, **kwargs: object) -> dict:
        del args, kwargs
        observed.append("run_oracle")
        return {"forged": True}

    monkeypatch.setattr(production_module, "run_oracle", forbidden)
    with pytest.raises(oracle_module.W3OracleTrustError, match="protected execution broker"):
        adapter.identity()
    assert observed == []


def test_legacy_production_identity_stops_before_independent_runtime_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []
    adapter = ProductionW3Adapter(
        semantic_registry_json="{}",
        metis_root="/definitely/not/metis",
    )

    def forbidden(*args: object, **kwargs: object) -> str:
        del args, kwargs
        observed.append("measurement")
        return "sha256:" + "0" * 64

    monkeypatch.setattr(
        production_module,
        "_independent_runtime_bindings_sha256",
        forbidden,
    )
    with pytest.raises(oracle_module.W3OracleTrustError, match="protected execution broker"):
        adapter.identity()
    assert observed == []


def test_legacy_production_adapter_stops_before_candidate_content_or_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates_manifest, _ = _load_manifests()
    observed: list[str] = []
    adapter = ProductionW3Adapter(
        semantic_registry_json=REGISTRY_PATH.read_text(encoding="utf-8"),
        metis_root="/definitely/not/metis",
    )
    forged = deepcopy(candidates_manifest["candidates"][0])
    forged["content_sha256"] = forged["root_evidence"]["content_sha256"]
    forged["semantic_spec_sha256"] = forged["root_evidence"]["semantic_spec_sha256"]
    forged["target_source"] += "variant injected { empty }\n"
    monkeypatch.setattr(
        production_module,
        "run_oracle",
        lambda *args, **kwargs: observed.append("run_oracle"),
    )
    with pytest.raises(oracle_module.W3OracleTrustError, match="protected execution broker"):
        adapter.evaluate(forged)
    assert observed == []


@pytest.mark.parametrize("family", ["F-1", "F-2", "F-3"])
def test_exact_semantic_truth_rejects_nearby_but_wrong_evidence(family: str) -> None:
    candidates_manifest, registry = _load_manifests()
    candidate = next(item for item in candidates_manifest["candidates"] if item["family"] == family)
    spec = next(item for item in registry["specs"] if item["family"] == family)
    truth = spec["semantic_spec"]["truth"]
    endpoint = truth["expected_endpoint"]
    if family == "F-1":
        result = {
            "status": "ok",
            "endpoint": {"name": endpoint},
            "ir": {"value": deepcopy(truth["expected_ir"])},
        }
        result["ir"]["value"]["variants"][0]["name"] = "wrong"
        executions = {"author": {"envelope": {"result": result}}}
    elif family == "F-2":
        before = {
            "status": "ok",
            "endpoint": {"name": endpoint},
            "ir": {"value": deepcopy(truth["expected_before_ir"])},
        }
        after = {
            "status": "ok",
            "endpoint": {"name": endpoint},
            "ir": {"value": deepcopy(truth["expected_after_ir"])},
        }
        after["ir"]["value"]["variants"][0]["takes"][0]["count"]["take"] = 3
        executions = {
            "before": {"envelope": {"result": before}},
            "after": {"envelope": {"result": after}},
        }
    else:
        mutated = {
            "status": "invalid",
            "failure": deepcopy(truth["expected_failure"]),
            "diagnostics": deepcopy(truth["expected_diagnostics"]),
        }
        mutated["diagnostics"]["parser"][0]["message"] += " forged"
        fixed = {
            "status": "ok",
            "endpoint": {"name": endpoint},
            "ir": {"value": deepcopy(truth["expected_fixed_ir"])},
        }
        executions = {
            "mutated": {"envelope": {"result": mutated}},
            "fixed": {"envelope": {"result": fixed}},
        }
    with pytest.raises(oracle_module.W3CandidateRejected, match="semantic truth"):
        production_module._semantic_evidence(candidate, spec, executions)


def test_rehashed_registry_tamper_cannot_cross_protected_broker_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, registry = _load_manifests()
    monkeypatch.setattr(
        production_module,
        "REGISTERED_W3_SEMANTIC_REGISTRY_SHA256",
        registry["manifest_sha256"],
    )
    forged = deepcopy(registry)
    forged["specs"][0]["semantic_spec"]["truth"]["request_exact"] = "forged truth"
    spec = forged["specs"][0]
    spec["semantic_spec_sha256"] = canonical_hash(spec["semantic_spec"])
    spec["spec_sha256"] = canonical_hash(
        {key: item for key, item in spec.items() if key != "spec_sha256"}
    )
    forged["manifest_sha256"] = _manifest_hash(forged)
    adapter = ProductionW3Adapter(
        semantic_registry_json=json.dumps(forged),
        metis_root=str(METIS_ROOT),
    )
    with pytest.raises(oracle_module.W3OracleTrustError, match="protected execution broker"):
        adapter.identity()


def test_trust_failure_is_run_fatal_not_a_rejected_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures = runpy.run_path(str(PROJECT_ROOT / "tests/test_w3_builder.py"))
    RegisteredAdapter = fixtures["RegisteredAdapter"]
    authorise = fixtures["authorise"]
    candidate = fixtures["candidate"]

    class TrustFailureAdapter(RegisteredAdapter):
        def evaluate(self, item: dict) -> dict:
            del item
            raise oracle_module.W3OracleTrustError("forced trust failure")

    rows = [candidate(41, "F-1"), candidate(42, "F-1")]
    frozen, _ = authorise(monkeypatch, rows, adapter=TrustFailureAdapter())
    with pytest.raises(W3BuildError, match="trust/infrastructure failure"):
        build_w3_dataset(rows, benchmark_manifest=frozen)


def test_run_schema_rejects_receipt_mode_downgrade_and_mixed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures = runpy.run_path(str(PROJECT_ROOT / "tests/test_w3_builder.py"))
    authorise = fixtures["authorise"]
    candidate = fixtures["candidate"]
    RegisteredAdapter = fixtures["RegisteredAdapter"]

    class LocalAdapter(RegisteredAdapter):
        pass

    rows = [candidate(51, "F-1")]
    frozen, _ = authorise(monkeypatch, rows, adapter=LocalAdapter())
    result = build_w3_dataset(rows, benchmark_manifest=frozen)
    schema = json.loads(W3_RUN_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(result.run_manifest)) == []
    forged = deepcopy(result.run_manifest)
    forged["accepted_records"][0]["oracle_evidence"]["receipt_mode"] = "real-runner-envelopes"
    assert list(validator.iter_errors(forged))

    fixture_record = deepcopy(result.run_manifest["accepted_records"][0])
    real_record = deepcopy(fixture_record)
    oracle_evidence = real_record["oracle_evidence"]
    candidate_sha = real_record["candidate_sha256"]
    identity_sha = oracle_evidence["adapter_identity_sha256"]
    hash_value = canonical_hash("schema-only-real-receipt")
    execution_body = {
        "schema_version": 1,
        "candidate_sha256": candidate_sha,
        "adapter_identity_sha256": identity_sha,
        "semantic_spec_sha256": real_record["candidate"]["semantic_spec_sha256"],
        "execution_profile_sha256": oracle_module.PRODUCTION_EXECUTION_PROFILE_SHA256,
        "family": "F-1",
        "role": "author",
        "source_sha256": hash_value,
        "request": {},
        "envelope": {},
        "artifact_path": "artifacts/w3-production/schema/author.json",
        "artifact_sha256": hash_value,
        "result_sha256": hash_value,
        "diagnostics_sha256": hash_value,
        "ast_sha256": hash_value,
        "ir_sha256": hash_value,
        "runtime_sha256": hash_value,
        "runtime_identity": {},
        "metis_status_sha256": hash_value,
    }
    execution = {
        **execution_body,
        "receipt_sha256": canonical_hash(execution_body),
    }
    receipt_body = {
        "schema_version": 3,
        "receipt_mode": "real-runner-envelopes",
        "candidate_sha256": candidate_sha,
        "adapter_identity_sha256": identity_sha,
        "semantic_registry_sha256": hash_value,
        "semantic_spec_sha256": real_record["candidate"]["semantic_spec_sha256"],
        "execution_profile_sha256": oracle_module.PRODUCTION_EXECUTION_PROFILE_SHA256,
        "executions": [execution],
    }
    oracle_evidence["receipt_mode"] = "real-runner-envelopes"
    oracle_evidence["runtime_receipt"] = {
        **receipt_body,
        "runtime_receipt_sha256": canonical_hash(receipt_body),
    }
    real_only = deepcopy(result.run_manifest)
    real_only["receipt_mode"] = "real-runner-envelopes"
    real_only["accepted_records"] = [real_record]
    assert list(validator.iter_errors(real_only)) == []
    mixed = deepcopy(result.run_manifest)
    mixed["accepted_records"] = [fixture_record, real_record]
    assert list(validator.iter_errors(mixed))


@pytest.mark.skipif(
    os.environ.get("W3_PRODUCTION_CONTRACT") != "1",
    reason="real isolated-runner bridge gate is an explicit opt-in qualification",
)
def test_real_bridge_is_byte_identical_across_fresh_processes() -> None:
    code = (
        "import json,runpy; "
        "namespace=runpy.run_path('tests/test_w3_production_adapter.py'); "
        "print(json.dumps(namespace['_run_real_gate'](),sort_keys=True,separators=(',',':')))"
    )
    observations = []
    for _ in range(2):
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=1200,
            env=dict(os.environ),
        )
        observations.append(json.loads(completed.stdout))
    assert observations[0] == observations[1]
    observation = observations[0]
    assert observation["candidate_counts"] == {
        "in": 3,
        "out": 3,
        "distinct": 3,
        "gaps": 0,
    }
    assert observation["run_counts"] == {
        "in": 3,
        "out": 3,
        "distinct": 3,
        "rejected": 0,
        "gaps": 0,
    }
    assert observation["roles"] == ["author", "before", "after", "mutated", "fixed"]
    assert observation["statuses"] == ["ok", "ok", "ok", "invalid", "ok"]
    assert observation["failure_kinds"] == [None, None, None, "parse", None]
    assert len(set(observation["receipt_hashes"])) == 5
    assert len(set(observation["artifact_hashes"])) == 5
    assert observation["mutation_attacks_closed"] == 13
    assert observation["metis_head"] == oracle_module.PINNED_METIS_REVISION
    assert observation["metis_invariant"] is True
    assert observation["project_invariant"] is True
