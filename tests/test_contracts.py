from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from copy import deepcopy

import pytest

import metis_model1.contracts as contracts
from metis_model1.contracts import (
    load_json,
    repository_root,
    validate_accuracy_target_contract,
    validate_artifact_policy_paths,
    validate_artifact_store_policy_contract,
    validate_benchmark_plan_contract,
    validate_foundation,
    validate_grammar_stdlib_t30_preoutput_contract,
    validate_grammar_stdlib_t30_successor_contract,
    validate_hyperparameter_grid_contract,
    validate_instance,
    validate_qualification_contract,
    validate_repository_file_contents,
    validate_w3_retained_report_schema_contract,
)


def test_repository_foundation_is_valid() -> None:
    report = validate_foundation(repository_root())
    assert report.errors == []
    assert "schema=schemas/w3-bridge-replay.schema.json" in report.passes
    assert "schema=schemas/w3-production-authority.schema.json" in report.passes
    assert "schema=schemas/w3-qualification.schema.json" in report.passes
    assert "schema=schemas/w3-native-loader-evidence.schema.json" in report.passes
    assert "schema=schemas/w3-semantic-spec.schema.json" in report.passes
    assert "schema=schemas/w3-source-register.schema.json" in report.passes
    assert "schema=schemas/w3-run.schema.json" in report.passes
    assert "contract=manifests/w1-slice-30-blocker-map-v1.json" in report.passes
    assert "contract=manifests/w2-rights-dossier-v1.json" in report.passes
    assert "contract=manifests/w1-slice-30-oracle-receipts-v1.json" in report.passes
    assert "contract=manifests/w1-leakage-group-assignment-v1.json" in report.passes
    assert "contract=manifests/w1-held-out-family-map-v1.json" in report.passes
    assert "contract=manifests/w1-benchmark-seal-v1.json" in report.passes
    assert "contract=manifests/catalog-maintenance-probe-evaluation-v1.json" in report.passes
    assert "contract=manifests/catalog-maintenance-probe-decision-v1.json" in report.passes
    assert "contract=manifests/catalog-maintenance-successor-probe-v1.json" in report.passes
    assert "contract=manifests/initial-local-qlora-plan-v1.json" in report.passes
    assert "catalog-retrieval-refresh=public-synthetic/8-goldens/redacted" in report.passes
    assert (
        "catalog-maintenance-probe=8-cases/evaluated/diagnose-2-of-8/output-observed"
        in report.passes
    )
    assert any(
        item.startswith("catalog-maintenance-successor=8-cases/") and item.endswith("/no-training")
        for item in report.passes
    )
    assert any(item.startswith("catalog-maintenance-successor-evidence=") for item in report.passes)
    assert "w1-w2-evidence-package=6-semantic-sidecars" in report.passes
    assert any(item.startswith("grammar-stdlib-t30-v2=adjudication/") for item in report.passes)
    assert any(
        item.startswith(
            tuple(
                f"grammar-stdlib-t30-v3={phase}/"
                for phase in ("truth", "freeze", "evaluation", "adjudication")
            )
        )
        for item in report.passes
    )
    assert "W1" not in report.open_by_wave
    assert "W4" not in report.open_by_wave
    assert report.open_nonblocking == ["O-009"]


def test_foundation_rejects_semantic_w2_rights_laundering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = repository_root()
    original = contracts.load_json

    def drifted(path):
        value = original(path)
        if path.name == "w2-rights-dossier-v1.json":
            value = deepcopy(value)
            value["assets"][0]["license"] = "invented-rights-claim"
        return value

    monkeypatch.setattr(contracts, "load_json", drifted)

    report = contracts.validate_foundation(root)

    assert "w2-rights-dossier: dossier field drift: assets" in report.errors


@pytest.mark.parametrize(
    ("schema_name", "variant_names"),
    [
        ("w3-production-authority.schema.json", (None,)),
        (
            "w3-qualification.schema.json",
            ("productionQualified", "productionBlocked"),
        ),
        ("w3-bridge-replay.schema.json", ("qualified", "blocked")),
    ],
)
def test_l66_production_schemas_bind_exact_native_evidence_manifest(
    schema_name: str,
    variant_names: tuple[str | None, ...],
) -> None:
    root = repository_root()
    manifest = load_json(root / "manifests/w3-native-loader-evidence.json")
    schema = load_json(root / "schemas" / schema_name)
    expected = {
        "const": {
            "path": "manifests/w3-native-loader-evidence.json",
            "manifest_sha256": manifest["manifest_sha256"],
        }
    }
    assert schema["$defs"]["nativeEvidence"] == expected
    for variant_name in variant_names:
        target = schema if variant_name is None else schema["$defs"][variant_name]
        assert "native_evidence" in target["required"]
        assert target["properties"]["native_evidence"] == {"$ref": "#/$defs/nativeEvidence"}


def test_w3_source_checkpoint_revision_is_repeated_exactly_across_four_paths() -> None:
    root = repository_root()
    expected = "5a5d817bb3df817fbd5d47b7bc4edd4517f8d9b7"
    former = "4ec625fcec8a9c41423bc048688d17775e57353c"
    paths = (
        root / "runtime/w3_bridge_gate.py",
        root / "runtime/w3_qualifier.py",
        root / "schemas/w3-production-authority.schema.json",
        root / "schemas/w3-qualification.schema.json",
    )
    assert [path.read_text().count(expected) for path in paths] == [1, 1, 1, 1]
    assert all(former not in path.read_text() for path in paths)


def test_w3_report_schemas_require_deferred_cleanup_on_all_six_variants() -> None:
    root = repository_root()
    qualification = load_json(root / "schemas/w3-qualification.schema.json")
    bridge = load_json(root / "schemas/w3-bridge-replay.schema.json")

    qualifier_variants = [
        qualification["$defs"][name]
        for name in ("qualified", "blocked", "productionQualified", "productionBlocked")
    ]
    bridge_variants = [bridge["$defs"][name] for name in ("qualified", "blocked")]

    assert all("cleanup" in variant["required"] for variant in qualifier_variants)
    assert all("cleanup" in variant["required"] for variant in bridge_variants)
    assert qualification["$defs"]["cleanup"]["properties"]["delete_attempts"] == {"const": 0}
    assert bridge["$defs"]["cleanup"]["properties"]["delete_attempts"] == {"const": 0}
    assert qualification["$defs"]["qualified"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/qualifiedV1Cleanup"
    }
    assert qualification["$defs"]["productionQualified"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/qualifiedV3Cleanup"
    }
    assert qualification["$defs"]["blocked"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/blockedV1Cleanup"
    }
    assert qualification["$defs"]["productionBlocked"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/blockedV3Cleanup"
    }
    assert bridge["$defs"]["qualified"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/qualifiedReplayCleanup"
    }
    assert bridge["$defs"]["blocked"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/blockedReplayCleanup"
    }
    assert bridge["$defs"]["physicalRun"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/qualifiedChildCleanup"
    }
    assert bridge["$defs"]["blockedObservedRun"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/blockedChildCleanup"
    }
    assert [
        item["$ref"]
        for item in bridge["$defs"]["blocked"]["properties"]["observed_runs"]["prefixItems"]
    ] == ["#/$defs/observedRun1", "#/$defs/observedRun2"]
    assert validate_w3_retained_report_schema_contract(root) == []


def test_ratified_benchmark_plan_has_six_families_and_thirty_distinct_allocations() -> None:
    root = repository_root()
    plan = load_json(root / "manifests/benchmark-plan.json")

    assert validate_benchmark_plan_contract(root) == []
    assert {family["id"] for family in plan["families"]} == {
        "F-1",
        "F-2",
        "F-3",
        "F-4",
        "F-5",
        "F-6",
    }
    assert len(plan["slice_30"]["tasks"]) == 30
    assert len({task["source_blob_oid"] for task in plan["slice_30"]["tasks"]}) == 30


def test_accuracy_target_is_pre_registered_and_arithmetically_consistent() -> None:
    root = repository_root()
    target = load_json(root / "manifests/accuracy-target.json")

    assert validate_accuracy_target_contract(root) == []
    assert target["registered_before_candidate_results"] is True
    assert target["status"] == "proposed"
    assert sum(target["family_counts"].values()) == target["total"] == 600
    assert target["maximum_failures"] == 1
    assert target["minimum_distinct_leakage_groups"] == 563


def test_accuracy_target_schema_rejects_post_result_registration() -> None:
    root = repository_root()
    schema = load_json(root / "schemas/accuracy-target.schema.json")
    target = deepcopy(load_json(root / "manifests/accuracy-target.json"))
    target["registered_before_candidate_results"] = False

    errors = validate_instance(target, schema)

    assert any("True was expected" in error for error in errors)


def test_grammar_stdlib_t30_preoutput_contract_is_fail_closed() -> None:
    assert validate_grammar_stdlib_t30_preoutput_contract(repository_root()) == []


def test_grammar_stdlib_t30_preoutput_contract_rejects_model_output_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = repository_root()
    original = contracts.load_json

    def drifted(path):
        value = original(path)
        if path.name == "grammar-stdlib-accuracy-t30-policy-v1.json":
            value = deepcopy(value)
            value["model_outputs_observed"] = True
        return value

    monkeypatch.setattr(contracts, "load_json", drifted)

    assert "T30 pre-output policy model_outputs_observed is not fail-closed" in (
        validate_grammar_stdlib_t30_preoutput_contract(root)
    )


def test_grammar_stdlib_t30_preoutput_contract_rejects_roster_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = repository_root()
    original = contracts.load_json

    def drifted(path):
        value = original(path)
        if path.name == "t30-tasks.json":
            value = deepcopy(value)
            value["tasks"][1]["task_id"] = value["tasks"][0]["task_id"]
        return value

    monkeypatch.setattr(contracts, "load_json", drifted)

    assert "T30 roster task IDs are not exactly thirty distinct tasks" in (
        validate_grammar_stdlib_t30_preoutput_contract(root)
    )


def test_grammar_stdlib_t30_preoutput_contract_rejects_out_of_order_stage(
    tmp_path,
) -> None:
    root = repository_root()
    for relative in (
        "fixtures/grammar-stdlib-accuracy-v1/t30-tasks.json",
        "fixtures/grammar-stdlib-accuracy-v1/t30-reference-context.md",
        "manifests/grammar-stdlib-accuracy-t30-policy-v1.json",
        "src/metis_model1/grammar_stdlib_t30.py",
        "tests/test_grammar_stdlib_t30.py",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination)
    freeze_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-freeze-v1.json"
    freeze_path.write_text("{}", encoding="utf-8")

    errors = validate_grammar_stdlib_t30_preoutput_contract(tmp_path)

    assert "T30 phase freeze is present before its predecessor" in errors


def test_grammar_stdlib_t30_successor_contract_is_fail_closed() -> None:
    root = repository_root()
    errors = validate_grammar_stdlib_t30_successor_contract(root)
    truth_path = root / "manifests/grammar-stdlib-accuracy-t30-truth-v3.json"

    if truth_path.is_file():
        assert errors == []
    else:
        assert errors == [
            "T30-v3 contract path is missing: manifests/grammar-stdlib-accuracy-t30-truth-v3.json"
        ]


def test_grammar_stdlib_t30_successor_rejects_out_of_order_stage(tmp_path) -> None:
    root = repository_root()
    for relative in (
        "fixtures/grammar-stdlib-accuracy-v2/t30-tasks.json",
        "fixtures/grammar-stdlib-accuracy-v2/t30-reference-context.md",
        "manifests/grammar-stdlib-accuracy-t30-policy-v2.json",
        "manifests/grammar-stdlib-accuracy-t30-evaluation-v1.json",
        "src/metis_model1/grammar_stdlib_t30.py",
        "src/metis_model1/grammar_stdlib_t30_successor.py",
        "tests/test_grammar_stdlib_t30_successor.py",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination)
    freeze_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-freeze-v2.json"
    freeze_path.write_text("{}", encoding="utf-8")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v2 phase freeze is present before its predecessor" in errors


def test_grammar_stdlib_t30_successor_rejects_policy_self_hash_drift(tmp_path) -> None:
    root = repository_root()
    static_paths = (
        "fixtures/grammar-stdlib-accuracy-v2/t30-tasks.json",
        "fixtures/grammar-stdlib-accuracy-v2/t30-reference-context.md",
        "manifests/grammar-stdlib-accuracy-t30-policy-v2.json",
        "manifests/grammar-stdlib-accuracy-t30-evaluation-v1.json",
        "src/metis_model1/grammar_stdlib_t30.py",
        "src/metis_model1/grammar_stdlib_t30_successor.py",
        "tests/test_grammar_stdlib_t30_successor.py",
    )
    for relative in static_paths:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination)
    policy_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-policy-v2.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["scope"] = "forged-after-ratification"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert any("policy_sha256 does not match canonical body" in error for error in errors)


def test_grammar_stdlib_t30_successor_rejects_rehashed_truth_input_drift(tmp_path) -> None:
    root = repository_root()
    for relative in (
        "fixtures/grammar-stdlib-accuracy-v2/t30-tasks.json",
        "fixtures/grammar-stdlib-accuracy-v2/t30-reference-context.md",
        "manifests/grammar-stdlib-accuracy-t30-policy-v2.json",
        "manifests/grammar-stdlib-accuracy-t30-truth-v2.json",
        "manifests/grammar-stdlib-accuracy-t30-evaluation-v1.json",
        "src/metis_model1/grammar_stdlib_t30.py",
        "src/metis_model1/grammar_stdlib_t30_successor.py",
        "tests/test_grammar_stdlib_t30_successor.py",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination)
    truth_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-truth-v2.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    truth["tasks_file_sha256"] = "sha256:" + "0" * 64
    body = {key: value for key, value in truth.items() if key != "truth_sha256"}
    truth["truth_sha256"] = hashlib.sha256(
        json.dumps(
            body,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    truth["truth_sha256"] = "sha256:" + truth["truth_sha256"]
    truth_path.write_text(json.dumps(truth), encoding="utf-8")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v2 truth tasks_file_sha256 does not link its input" in errors


def _copy_t30_v3_static_contract(tmp_path) -> None:
    root = repository_root()
    for relative in (
        "fixtures/grammar-stdlib-accuracy-v2/t30-tasks.json",
        "fixtures/grammar-stdlib-accuracy-v2/t30-reference-context.md",
        "manifests/grammar-stdlib-accuracy-t30-policy-v2.json",
        "manifests/grammar-stdlib-accuracy-t30-evaluation-v1.json",
        "fixtures/grammar-stdlib-accuracy-v3/t30-tasks.json",
        "fixtures/grammar-stdlib-accuracy-v3/t30-reference-context.md",
        "manifests/grammar-stdlib-accuracy-t30-policy-v3.json",
        "manifests/grammar-stdlib-accuracy-t30-truth-v2.json",
        "manifests/grammar-stdlib-accuracy-t30-freeze-v2.json",
        "manifests/grammar-stdlib-accuracy-t30-evaluation-v2.json",
        "manifests/grammar-stdlib-accuracy-t30-adjudication-v2.json",
        "src/metis_model1/grammar_stdlib_t30.py",
        "src/metis_model1/grammar_stdlib_t30_successor.py",
        "src/metis_model1/grammar_stdlib_t30_v3.py",
        "tests/test_grammar_stdlib_t30_successor.py",
        "tests/test_grammar_stdlib_t30_v3.py",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination)
    from metis_model1 import grammar_stdlib_t30 as t30
    from metis_model1 import grammar_stdlib_t30_v3 as v3

    with v3.successor_configuration():
        bound_paths = tuple(t30.BOUND_PATHS)
    for relative in bound_paths:
        source = root / relative
        destination = tmp_path / relative
        if source.is_file() and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    policy_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-policy-v3.json"
    policy_value = json.loads(policy_path.read_text(encoding="utf-8"))
    policy_value["nonclaims"] = v3.V3_NONCLAIMS
    policy_path.write_text(json.dumps(policy_value), encoding="utf-8")
    _rewrite_canonical_self_hash(policy_path, "policy_sha256")
    truth_path = root / "manifests/grammar-stdlib-accuracy-t30-truth-v3.json"
    destination = tmp_path / "manifests/grammar-stdlib-accuracy-t30-truth-v3.json"
    if truth_path.is_file():
        shutil.copy2(truth_path, destination)
        return

    policy = json.loads(
        (tmp_path / "manifests/grammar-stdlib-accuracy-t30-policy-v3.json").read_text()
    )
    predecessor_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-evaluation-v2.json"
    predecessor_raw = predecessor_path.read_bytes()
    predecessor_value = json.loads(predecessor_raw)
    predecessor = {
        "path": "manifests/grammar-stdlib-accuracy-t30-evaluation-v2.json",
        "bytes": len(predecessor_raw),
        "file_sha256": "sha256:" + hashlib.sha256(predecessor_raw).hexdigest(),
        "evaluation_sha256": predecessor_value["evaluation_sha256"],
        "verdict": predecessor_value["decision"]["verdict"],
        "disposition": "terminal_diagnosis_no_promotion",
    }
    tasks = json.loads(
        (tmp_path / "fixtures/grammar-stdlib-accuracy-v3/t30-tasks.json").read_text()
    )["tasks"]
    with v3.successor_configuration():

        def signature(task, *, invalid: bool = False):
            mode = task["oracle"]["mode"]
            return {
                "contract": "metis-semantic-signature/v2",
                "status": "invalid" if invalid else "ok",
                "endpoint": {
                    "mode": mode,
                    "requested": task["oracle"].get("target") if mode == "endpoint" else None,
                    "selected": task["oracle"].get("target") if mode == "endpoint" else None,
                    "count": 1 if mode == "endpoint" else 0,
                },
                "semantic_ast_sha256": "sha256:" + "a" * 64,
                "semantic_ir_sha256": None if invalid else "sha256:" + "b" * 64,
                "semantic_diagnostics_sha256": "sha256:" + "c" * 64,
                "failure_kind": task["oracle"].get("input_failure_kind") if invalid else None,
            }

        records = []
        for task in tasks:
            target = {
                "kind": task["task_mode"],
                "authority_tier": task["authority_tier"],
                "messages_sha256": t30.canonical_hash(t30.build_messages(task)),
                "declared_coverage": task["coverage"],
                "content_root_sha256": t30._task_content_root(task),
                "before": (
                    signature(task, invalid=task["oracle"].get("input_failure_kind") is not None)
                    if task.get("before_source") is not None
                    else None
                ),
                "input": signature(task) if task.get("input_source") is not None else None,
                "repaired": signature(task)
                if task.get("expected_repaired_source") is not None
                else None,
                "expected_coverage": task["coverage"],
            }
            if task["task_mode"] == "source_output":
                target["expected"] = signature(task)
            else:
                target["expected_json_sha256"] = t30.canonical_hash(task["expected_json"])
            records.append(
                {
                    "task_id": task["task_id"],
                    "family": task["family"],
                    "authority_tier": task["authority_tier"],
                    "target": target,
                    "model_output_observed": False,
                }
            )
        truth = {
            "schema_version": 1,
            "truth_id": t30.TRUTH_ID,
            "status": "truth_fixed_before_model_output",
            "authority_tier": "automatic",
            "benchmark_id": t30.BENCHMARK_ID,
            "semantic_signature_contract": t30.d18.SEMANTIC_SIGNATURE_CONTRACT,
            "tasks_file_sha256": "sha256:"
            + hashlib.sha256(
                (tmp_path / "fixtures/grammar-stdlib-accuracy-v3/t30-tasks.json").read_bytes()
            ).hexdigest(),
            "reference_context_sha256": "sha256:"
            + hashlib.sha256(
                (
                    tmp_path / "fixtures/grammar-stdlib-accuracy-v3/t30-reference-context.md"
                ).read_bytes()
            ).hexdigest(),
            "policy_sha256": policy["policy_sha256"],
            "grammar_stdlib_pin": json.loads(
                (tmp_path / "manifests/grammar-stdlib-accuracy-t30-truth-v2.json").read_text(
                    encoding="utf-8"
                )
            )["grammar_stdlib_pin"],
            "generation": t30.GENERATION,
            "thresholds": t30.THRESHOLDS,
            "counts": {
                "tasks_in": 30,
                "tasks_out": 30,
                "tasks_distinct": 30,
                "gaps": 0,
                "families": {family: 5 for family in t30.FAMILIES},
            },
            "tasks": records,
            "model_outputs_observed": False,
            "training_authorized": False,
            "delta_qlora_authorized": False,
            "nonclaims": policy["nonclaims"],
            "predecessor_terminal_diagnosis": predecessor,
        }
    truth["truth_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                truth, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )
    destination.write_text(json.dumps(truth), encoding="utf-8")


def _rewrite_canonical_self_hash(path, field: str) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    body = {key: item for key, item in value.items() if key != field}
    value[field] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                body,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


def test_grammar_stdlib_t30_v3_rejects_out_of_order_phase(tmp_path) -> None:
    _copy_t30_v3_static_contract(tmp_path)
    evaluation_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-evaluation-v3.json"
    evaluation_path.write_text("{}", encoding="utf-8")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v3 phase evaluation is present before its predecessor" in errors


def test_grammar_stdlib_t30_v3_synthetic_static_contract_is_valid(tmp_path) -> None:
    _copy_t30_v3_static_contract(tmp_path)

    assert validate_grammar_stdlib_t30_successor_contract(tmp_path) == []


def _write_t30_v3_complete_phase_fixture(tmp_path, *, passing: bool = False) -> None:
    """Materialize a realistic local phase chain with raw candidate/report lineage."""

    _copy_t30_v3_static_contract(tmp_path)
    from metis_model1 import grammar_stdlib_t30 as t30
    from metis_model1 import grammar_stdlib_t30_v3 as v3

    policy_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-policy-v3.json"
    truth_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-truth-v3.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    truth_by_id = {row["task_id"]: row for row in truth["tasks"]}
    tasks = json.loads(
        (tmp_path / "fixtures/grammar-stdlib-accuracy-v3/t30-tasks.json").read_text(
            encoding="utf-8"
        )
    )["tasks"]
    with v3.successor_configuration():
        freeze_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-freeze-v3.json"
        freeze = {
            "schema_version": 1,
            "freeze_id": t30.FREEZE_ID,
            "status": "frozen_before_model_output",
            "authority_tier": "automatic",
            "preimage_commit": "0" * 40,
            "preimage_tree": "1" * 40,
            "remote": "synthetic-test",
            "remote_ref": "synthetic-test-ref",
            "run_id": t30.RUN_ID,
            "run_dir": t30.RUN_RELATIVE,
            "attempt_nonce": t30.ATTEMPT_NONCE,
            "bound_inputs": [
                contracts._t30_v3_bound_record(tmp_path, path) for path in t30.BOUND_PATHS
            ],
            "truth_sha256": truth["truth_sha256"],
            "policy_sha256": policy["policy_sha256"],
            "policy_file_sha256": "sha256:" + hashlib.sha256(policy_path.read_bytes()).hexdigest(),
            "tasks_file_sha256": "sha256:"
            + hashlib.sha256(
                (tmp_path / "fixtures/grammar-stdlib-accuracy-v3/t30-tasks.json").read_bytes()
            ).hexdigest(),
            "reference_context_sha256": "sha256:"
            + hashlib.sha256(
                (
                    tmp_path / "fixtures/grammar-stdlib-accuracy-v3/t30-reference-context.md"
                ).read_bytes()
            ).hexdigest(),
            "semantic_signature_contract": t30.d18.SEMANTIC_SIGNATURE_CONTRACT,
            "runtime_identities": json.loads(
                (tmp_path / "manifests/grammar-stdlib-accuracy-t30-freeze-v2.json").read_text(
                    encoding="utf-8"
                )
            )["runtime_identities"],
            "generation": t30.GENERATION,
            "thresholds": t30.THRESHOLDS,
            "model_outputs_observed": False,
            "training_authorized": False,
            "delta_qlora_authorized": False,
            "nonclaims": policy["nonclaims"],
            "predecessor_terminal_diagnosis": truth["predecessor_terminal_diagnosis"],
        }
        freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
        freeze = _rewrite_canonical_self_hash(freeze_path, "freeze_sha256")

        empty_coverage = {field: [] for field in t30.COVERAGE_FIELDS}
        run_dir = tmp_path / t30.RUN_RELATIVE
        internal_observations: dict[str, list[dict]] = {}
        outputs: dict[str, dict] = {}
        for side in ("base", "adapter"):
            candidate_rows = [
                {
                    "task_id": task["task_id"],
                    "text": f"synthetic rejected {side} candidate for {task['task_id']}",
                    "peak_metal_gb": 0.125,
                }
                for task in tasks
            ]
            raw = b"".join(contracts._t30_v3_canonical_bytes(row) + b"\n" for row in candidate_rows)
            candidate_path = run_dir / side / "candidates.jsonl"
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.write_bytes(raw)
            outputs[side] = {
                "path": f"{t30.RUN_RELATIVE}/{side}/candidates.jsonl",
                "bytes": len(raw),
                "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            }
            internal_observations[side] = [
                {
                    "task_id": task["task_id"],
                    "family": task["family"],
                    "task_mode": task["task_mode"],
                    "authority_tier": task["authority_tier"],
                    "independent_root": task["provenance_roots"]["independent"],
                    "mechanical_match": passing,
                    "semantic_correct": (
                        passing if task["family"] in {"F-1", "F-2", "F-3", "F-4"} else None
                    ),
                    "final_human_review_required": task["family"] in t30.FINAL_HUMAN_REVIEW,
                    "final_human_review_kind": t30.FINAL_HUMAN_REVIEW.get(task["family"]),
                    "critical_failure": False,
                    "failure_code": None if passing else "semantic_mismatch",
                    "candidate_sha256": "sha256:"
                    + hashlib.sha256(candidate["text"].encode()).hexdigest(),
                    "observed": (
                        deepcopy(truth_by_id[task["task_id"]]["target"]["expected"])
                        if passing and task["task_mode"] == "source_output"
                        else {
                            "json": deepcopy(task["expected_json"]),
                            "json_sha256": t30.canonical_hash(task["expected_json"]),
                        }
                        if passing
                        else None
                    ),
                    "observed_coverage": deepcopy(task["coverage"]) if passing else empty_coverage,
                    "peak_metal_gb": candidate["peak_metal_gb"],
                }
                for task, candidate in zip(tasks, candidate_rows, strict=True)
            ]
        decision = t30.gate_arithmetic(
            internal_observations["base"], internal_observations["adapter"]
        )
        requests = t30._request_batch(tasks)
        attempt_path = run_dir / "attempt.json"
        attempt = {
            "schema_version": 1,
            "attempt_id": t30.ATTEMPT_NONCE,
            "status": "started_before_model_output",
            "head": "2" * 40,
            "tree": "3" * 40,
            "freeze_sha256": freeze["freeze_sha256"],
            "base_requests": 30,
            "adapter_requests": 30,
            "requests_sha256": t30.canonical_hash(requests),
            "request_ids_sha256": t30.canonical_hash([row["request_id"] for row in requests]),
            "base_worker_command": t30._worker_command(False),
            "adapter_worker_command": t30._worker_command(True),
            "runtime_identities_sha256": t30.canonical_hash(freeze["runtime_identities"]),
            "generation": t30.GENERATION,
            "model_outputs_observed": False,
            "training_authorized": False,
            "delta_qlora_authorized": False,
        }
        attempt["attempt_sha256"] = t30.canonical_hash(attempt)
        attempt_raw = contracts._t30_v3_canonical_bytes(attempt) + b"\n"
        attempt_path.write_bytes(attempt_raw)
        attempt_receipt = {
            "path": f"{t30.RUN_RELATIVE}/attempt.json",
            "bytes": len(attempt_raw),
            "sha256": "sha256:" + hashlib.sha256(attempt_raw).hexdigest(),
            "attempt_sha256": attempt["attempt_sha256"],
        }
        report = {
            "schema_version": 1,
            "status": "complete",
            "authority_tier": "diagnostic_only",
            "head": "2" * 40,
            "tree": "3" * 40,
            "freeze_sha256": freeze["freeze_sha256"],
            "attempt_nonce": t30.ATTEMPT_NONCE,
            "attempt_receipt": attempt_receipt,
            "outputs": outputs,
            "observations": internal_observations,
            "decision": decision,
            "model_outputs_observed": True,
            "training_authorized": False,
            "delta_qlora_authorized": False,
            "nonclaims": policy["nonclaims"],
        }
        report["report_sha256"] = t30.canonical_hash(report)
        (run_dir / "report.json").write_bytes(contracts._t30_v3_canonical_bytes(report) + b"\n")
        observations = t30._public_observations(internal_observations)
        evaluation_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-evaluation-v3.json"
        evaluation = {
            "schema_version": 1,
            "evidence_id": t30.EVIDENCE_ID,
            "status": "verified_local_cooperative",
            "authority_tier": "diagnostic_only",
            "execution": {
                "head": "2" * 40,
                "tree": "3" * 40,
                "freeze_sha256": freeze["freeze_sha256"],
                "freeze_file_sha256": "sha256:"
                + hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
                "report_sha256": report["report_sha256"],
                "run_dir": t30.RUN_RELATIVE,
                "outputs": outputs,
            },
            "observations": observations,
            "decision": decision,
            "model_outputs_observed": True,
            "training_authorized": False,
            "delta_qlora_authorized": False,
            "nonclaims": policy["nonclaims"],
        }
        evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
        evaluation = _rewrite_canonical_self_hash(evaluation_path, "evaluation_sha256")

        reviews = [
            {
                "task_id": task["task_id"],
                "family": task["family"],
                "review_kind": t30.FINAL_HUMAN_REVIEW[task["family"]],
                "candidate_sha256": observations["adapter"][index]["candidate_sha256"],
                "decision": "ACCEPT" if passing else "REJECT",
                "rationale_code": task["family"].replace("-", "")
                + ("_SYNTHETIC_ACCEPT" if passing else "_SYNTHETIC_REJECT"),
                "rationale": (
                    "Synthetic static fixture records a sufficiently detailed acceptance."
                    if passing
                    else "Synthetic static fixture records a sufficiently detailed rejection."
                ),
                "source": "direct_candidate_and_pinned_truth_review",
            }
            for index, task in enumerate(tasks)
            if task["family"] in t30.FINAL_HUMAN_REVIEW
        ]
        review_receipt = {
            "schema_version": 1,
            "review_id": t30.HUMAN_REVIEW_ID,
            "authority_tier": "human_review_required",
            "reviewer_role": "L0_frontier_coordinator",
            "evaluation_sha256": evaluation["evaluation_sha256"],
            "reviews": reviews,
        }
        review_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-human-review-v3.json"
        review_raw = contracts._t30_v3_canonical_bytes(review_receipt) + b"\n"
        review_path.write_bytes(review_raw)
        adjudication_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-adjudication-v3.json"
        adjudication = {
            "schema_version": 1,
            "adjudication_id": t30.ADJUDICATION_ID,
            "status": "final_local_adjudication",
            "authority_tier": "L0_frontier_human_review",
            "evaluation_sha256": evaluation["evaluation_sha256"],
            "evaluation_file_sha256": "sha256:"
            + hashlib.sha256(evaluation_path.read_bytes()).hexdigest(),
            "freeze_sha256": freeze["freeze_sha256"],
            "review_receipt_sha256": "sha256:" + hashlib.sha256(review_raw).hexdigest(),
            "reviews": reviews,
            "decision": t30._final_adjudication(evaluation, review_receipt, freeze),
            "model_outputs_observed": True,
            "training_authorized": False,
            "delta_qlora_authorized": False,
            "nonclaims": policy["nonclaims"],
        }
    adjudication_path.write_text(json.dumps(adjudication), encoding="utf-8")
    _rewrite_canonical_self_hash(adjudication_path, "adjudication_sha256")


def test_grammar_stdlib_t30_v3_realistic_complete_phase_contract_is_valid(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_t30_v3_complete_phase_fixture(tmp_path)
    evaluation = json.loads(
        (tmp_path / "manifests/grammar-stdlib-accuracy-t30-evaluation-v3.json").read_text()
    )
    monkeypatch.setattr(contracts, "_t30_v3_git_lineage", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        contracts,
        "_t30_v3_live_semantic_replay",
        lambda *_args, **_kwargs: deepcopy(evaluation["observations"]),
    )

    assert validate_grammar_stdlib_t30_successor_contract(tmp_path) == []


def test_grammar_stdlib_t30_v3_realistic_review_and_pass_chain_is_valid(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_t30_v3_complete_phase_fixture(tmp_path, passing=True)
    evaluation = json.loads(
        (tmp_path / "manifests/grammar-stdlib-accuracy-t30-evaluation-v3.json").read_text()
    )
    adjudication = json.loads(
        (tmp_path / "manifests/grammar-stdlib-accuracy-t30-adjudication-v3.json").read_text()
    )
    monkeypatch.setattr(contracts, "_t30_v3_git_lineage", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        contracts,
        "_t30_v3_live_semantic_replay",
        lambda *_args, **_kwargs: deepcopy(evaluation["observations"]),
    )

    assert evaluation["decision"]["verdict"] == "GRAMMAR_STDLIB_T30_V3_REVIEW_REQUIRED"
    assert adjudication["decision"]["verdict"] == "GRAMMAR_STDLIB_T30_V3_PASS_NO_RETRAIN"
    assert validate_grammar_stdlib_t30_successor_contract(tmp_path) == []


def test_t30_v3_git_lineage_binds_real_commits_blobs_and_freeze_bytes(tmp_path) -> None:
    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(tmp_path), *arguments],
            capture_output=True,
            check=True,
            text=True,
        )
        return completed.stdout.strip()

    git("init", "-q")
    git("config", "user.name", "T30 Contract Test")
    git("config", "user.email", "t30-contract@example.invalid")
    bound_path = tmp_path / "bound.txt"
    bound_path.write_text("sealed\n", encoding="utf-8")
    git("add", "bound.txt")
    git("commit", "-qm", "preimage")
    preimage = git("rev-parse", "HEAD")
    preimage_tree = git("rev-parse", "HEAD^{tree}")
    freeze = {
        "preimage_commit": preimage,
        "preimage_tree": preimage_tree,
        "bound_inputs": [contracts._t30_v3_bound_record(tmp_path, "bound.txt")],
    }
    freeze_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-freeze-v3.json"
    freeze_path.parent.mkdir()
    freeze_path.write_bytes(contracts._t30_v3_canonical_bytes(freeze) + b"\n")
    git("add", freeze_path.relative_to(tmp_path).as_posix())
    git("commit", "-qm", "run freeze")
    execution = {"head": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}")}

    assert (
        contracts._t30_v3_git_lineage(tmp_path, {"bound_paths": ["bound.txt"]}, freeze, execution)
        == []
    )

    synthetic_execution = {**execution, "head": "2" * 40}
    assert contracts._t30_v3_git_lineage(
        tmp_path, {"bound_paths": ["bound.txt"]}, freeze, synthetic_execution
    ) == ["T30-v3 Git lineage is unavailable or contains drift"]

    bound_path.write_text("mutated during run\n", encoding="utf-8")
    git("add", "bound.txt")
    git("commit", "-qm", "mutate bound input")
    mutated_execution = {
        "head": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
    }
    assert contracts._t30_v3_git_lineage(
        tmp_path, {"bound_paths": ["bound.txt"]}, freeze, mutated_execution
    ) == ["T30-v3 Git lineage is unavailable or contains drift"]


def test_t30_v3_git_lineage_rejects_unresolved_synthetic_oids(tmp_path) -> None:
    assert contracts._t30_v3_git_lineage(
        tmp_path,
        {"bound_paths": []},
        {
            "preimage_commit": "0" * 40,
            "preimage_tree": "1" * 40,
            "bound_inputs": [],
        },
        {"head": "2" * 40, "tree": "3" * 40},
    ) == ["T30-v3 Git lineage is unavailable or contains drift"]


def test_t30_v3_unpatched_garbage_diagnosis_fails_closed_before_oracle(tmp_path) -> None:
    _write_t30_v3_complete_phase_fixture(tmp_path)

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert any(error.startswith("T30-v3 live semantic replay is unavailable:") for error in errors)


@pytest.mark.parametrize(
    "surface",
    [
        "decision_null",
        "decision_empty",
        "adapter_null",
        "gates_null",
        "runtime_null",
        "adapter_off_restore_null",
    ],
)
def test_t30_v3_malformed_phase_surfaces_never_escape(
    tmp_path, monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    _write_t30_v3_complete_phase_fixture(tmp_path)
    evaluation_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-evaluation-v3.json"
    freeze_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-freeze-v3.json"
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if surface == "decision_null":
        evaluation["decision"] = None
    elif surface == "decision_empty":
        evaluation["decision"] = {}
    elif surface == "adapter_null":
        evaluation["decision"]["adapter"] = None
    elif surface == "gates_null":
        evaluation["decision"]["gates"] = None
    elif surface == "runtime_null":
        freeze["runtime_identities"] = None
    else:
        freeze["runtime_identities"]["adapter_off_restore"] = None
    evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
    monkeypatch.setattr(contracts, "_t30_v3_git_lineage", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        contracts,
        "_t30_v3_live_semantic_replay",
        lambda *_args, **_kwargs: deepcopy(evaluation["observations"]),
    )

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert errors
    assert any("malformed" in error or "drift" in error or "invalid" in error for error in errors)


def test_grammar_stdlib_t30_v3_rejects_rehashed_full_roster_pass_laundering(tmp_path) -> None:
    _write_t30_v3_complete_phase_fixture(tmp_path)
    from metis_model1 import grammar_stdlib_t30 as t30
    from metis_model1 import grammar_stdlib_t30_v3 as v3

    evaluation_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-evaluation-v3.json"
    adjudication_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-adjudication-v3.json"
    with v3.successor_configuration():
        evaluation_verdict = t30.PRE_REVIEW_VERDICT
        adjudication_verdict = t30.PASS_VERDICT
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    evaluation["decision"]["gates"] = {gate: True for gate in evaluation["decision"]["gates"]}
    evaluation["decision"]["verdict"] = evaluation_verdict
    evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
    evaluation = _rewrite_canonical_self_hash(evaluation_path, "evaluation_sha256")
    adjudication = json.loads(adjudication_path.read_text(encoding="utf-8"))
    adjudication["evaluation_sha256"] = evaluation["evaluation_sha256"]
    adjudication["evaluation_file_sha256"] = (
        "sha256:" + hashlib.sha256(evaluation_path.read_bytes()).hexdigest()
    )
    adjudication["decision"]["gates"] = {gate: True for gate in adjudication["decision"]["gates"]}
    adjudication["decision"]["verdict"] = adjudication_verdict
    adjudication_path.write_text(json.dumps(adjudication), encoding="utf-8")
    _rewrite_canonical_self_hash(adjudication_path, "adjudication_sha256")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v3 evaluation decision arithmetic or evidence linkage contains drift" in errors
    assert any(error.startswith("T30-v3 live semantic replay is unavailable:") for error in errors)


def test_grammar_stdlib_t30_v3_rejects_rehashed_grammar_stdlib_pin(tmp_path) -> None:
    _copy_t30_v3_static_contract(tmp_path)
    truth_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-truth-v3.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    truth["grammar_stdlib_pin"] = {"forged": "nonempty"}
    truth_path.write_text(json.dumps(truth), encoding="utf-8")
    _rewrite_canonical_self_hash(truth_path, "truth_sha256")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v3 truth static identity evidence contains drift" in errors


def test_grammar_stdlib_t30_v3_rejects_truth_self_hash_drift(tmp_path) -> None:
    _copy_t30_v3_static_contract(tmp_path)
    truth_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-truth-v3.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    truth["truth_sha256"] = "sha256:" + "0" * 64
    truth_path.write_text(json.dumps(truth), encoding="utf-8")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v3 truth self-hash is invalid" in errors


def test_grammar_stdlib_t30_v3_rejects_rehashed_predecessor_adjudication_drift(tmp_path) -> None:
    _copy_t30_v3_static_contract(tmp_path)
    adjudication_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-adjudication-v2.json"
    adjudication = json.loads(adjudication_path.read_text(encoding="utf-8"))
    adjudication["decision"]["verdict"] = "FORGED"
    _rewrite_canonical_self_hash(adjudication_path, "adjudication_sha256")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v3 predecessor does not bind final T30-v2 adjudication" in errors


def test_grammar_stdlib_t30_v3_rejects_rehashed_predecessor_truth_link_drift(tmp_path) -> None:
    _copy_t30_v3_static_contract(tmp_path)
    truth_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-truth-v3.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    truth["predecessor_terminal_diagnosis"]["evaluation_sha256"] = "sha256:" + "0" * 64
    truth_path.write_text(json.dumps(truth), encoding="utf-8")
    _rewrite_canonical_self_hash(truth_path, "truth_sha256")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v3 truth does not bind the terminal T30-v2 diagnosis" in errors


def test_grammar_stdlib_t30_v3_rejects_rehashed_counter_only_truth(tmp_path) -> None:
    _copy_t30_v3_static_contract(tmp_path)
    truth_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-truth-v3.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    truth["tasks"] = []
    truth_path.write_text(json.dumps(truth), encoding="utf-8")
    _rewrite_canonical_self_hash(truth_path, "truth_sha256")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v3 truth task roster is not exactly thirty rows" in errors


def test_grammar_stdlib_t30_v3_rejects_rehashed_empty_semantic_signature(tmp_path) -> None:
    _copy_t30_v3_static_contract(tmp_path)
    truth_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-truth-v3.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    truth["tasks"][0]["target"]["expected"] = {}
    truth_path.write_text(json.dumps(truth), encoding="utf-8")
    _rewrite_canonical_self_hash(truth_path, "truth_sha256")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v3 truth task target drift: gsl_t30v3_f1_01" in errors


def test_grammar_stdlib_t30_v3_rejects_rehashed_minimal_pass_promotion_chain(tmp_path) -> None:
    _copy_t30_v3_static_contract(tmp_path)
    policy_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-policy-v3.json"
    truth_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-truth-v3.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    freeze_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-freeze-v3.json"
    freeze = {
        "schema_version": 1,
        "freeze_id": "grammar-stdlib-accuracy-t30-freeze/v3",
        "status": "frozen_before_model_output",
        "authority_tier": "automatic",
        "truth_sha256": truth["truth_sha256"],
        "policy_sha256": policy["policy_sha256"],
        "nonclaims": policy["nonclaims"],
        "model_outputs_observed": False,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "tasks_file_sha256": "sha256:"
        + hashlib.sha256(
            (tmp_path / "fixtures/grammar-stdlib-accuracy-v3/t30-tasks.json").read_bytes()
        ).hexdigest(),
        "reference_context_sha256": "sha256:"
        + hashlib.sha256(
            (tmp_path / "fixtures/grammar-stdlib-accuracy-v3/t30-reference-context.md").read_bytes()
        ).hexdigest(),
        "policy_file_sha256": "sha256:" + hashlib.sha256(policy_path.read_bytes()).hexdigest(),
    }
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
    freeze = _rewrite_canonical_self_hash(freeze_path, "freeze_sha256")
    evaluation_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-evaluation-v3.json"
    evaluation = {
        "schema_version": 1,
        "evidence_id": "grammar-stdlib-accuracy-t30-evaluation/v3",
        "status": "verified_local_cooperative",
        "authority_tier": "diagnostic_only",
        "nonclaims": policy["nonclaims"],
        "model_outputs_observed": True,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "execution": {
            "freeze_sha256": freeze["freeze_sha256"],
            "freeze_file_sha256": "sha256:" + hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
        },
        "decision": {
            "verdict": "GRAMMAR_STDLIB_T30_V3_REVIEW_REQUIRED",
            "gates": {"complete": True},
            "training_authorized": False,
            "delta_qlora_authorized": False,
        },
    }
    evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
    evaluation = _rewrite_canonical_self_hash(evaluation_path, "evaluation_sha256")
    adjudication_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-adjudication-v3.json"
    adjudication = {
        "schema_version": 1,
        "adjudication_id": "grammar-stdlib-accuracy-t30-adjudication/v3",
        "status": "final_local_adjudication",
        "authority_tier": "L0_frontier_human_review",
        "evaluation_sha256": evaluation["evaluation_sha256"],
        "freeze_sha256": freeze["freeze_sha256"],
        "nonclaims": policy["nonclaims"],
        "model_outputs_observed": True,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "evaluation_file_sha256": "sha256:"
        + hashlib.sha256(evaluation_path.read_bytes()).hexdigest(),
        "reviews": [],
        "decision": {
            "verdict": "GRAMMAR_STDLIB_T30_V3_PASS_NO_RETRAIN",
            "gates": {"complete": True},
            "training_authorized": False,
            "delta_qlora_authorized": False,
            "promotion_authorized": "forged-string-authority",
        },
    }
    adjudication_path.write_text(json.dumps(adjudication), encoding="utf-8")
    _rewrite_canonical_self_hash(adjudication_path, "adjudication_sha256")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v3 freeze static evidence roster or linkage contains drift" in errors
    assert "T30-v3 evaluation execution evidence is incomplete" in errors
    assert "T30-v3 adjudication review/final-task roster is incomplete" in errors
    assert "T30-v3 phase decision/gate evidence is missing" in errors


def test_grammar_stdlib_t30_v3_rejects_freeze_predecessor_link_drift(tmp_path) -> None:
    _write_t30_v3_complete_phase_fixture(tmp_path)
    (tmp_path / "manifests/grammar-stdlib-accuracy-t30-evaluation-v3.json").unlink()
    (tmp_path / "manifests/grammar-stdlib-accuracy-t30-adjudication-v3.json").unlink()
    freeze_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-freeze-v3.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze["predecessor_terminal_diagnosis"] = {"forged": "promotable"}
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
    _rewrite_canonical_self_hash(freeze_path, "freeze_sha256")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v3 freeze static evidence roster or linkage contains drift" in errors


def test_grammar_stdlib_t30_v3_accepts_nonnegative_source_endpoint_count() -> None:
    root = repository_root()
    tasks = json.loads(
        (root / "fixtures/grammar-stdlib-accuracy-v3/t30-tasks.json").read_text(encoding="utf-8")
    )["tasks"]
    truth = json.loads(
        (root / "manifests/grammar-stdlib-accuracy-t30-truth-v3.json").read_text(encoding="utf-8")
    )
    task = next(row for row in tasks if row["oracle"]["mode"] == "source")
    truth_by_id = {row["task_id"]: row for row in truth["tasks"]}
    signature = deepcopy(truth_by_id[task["task_id"]]["target"]["expected"])
    signature["endpoint"]["count"] = 2

    assert contracts._is_t30_v3_semantic_signature(task, signature)
    signature["endpoint"]["count"] = -1
    assert not contracts._is_t30_v3_semantic_signature(task, signature)


def test_grammar_stdlib_t30_v3_malformed_observation_fails_without_exception(tmp_path) -> None:
    _write_t30_v3_complete_phase_fixture(tmp_path)
    evaluation_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-evaluation-v3.json"
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    del evaluation["observations"]["adapter"][0]["task_id"]
    evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
    _rewrite_canonical_self_hash(evaluation_path, "evaluation_sha256")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v3 evaluation observations are not a paired 30-task roster" in errors


def test_grammar_stdlib_t30_v3_rejects_candidate_artifact_drift(tmp_path) -> None:
    _write_t30_v3_complete_phase_fixture(tmp_path)
    candidate_path = (
        tmp_path / "artifacts/grammar-stdlib-accuracy/t30/t30-v3-20260826/base/candidates.jsonl"
    )
    candidate_path.write_bytes(candidate_path.read_bytes() + b"{}\n")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v3 base candidate artifact identity contains drift" in errors
    assert "T30-v3 base candidate roster is not exactly thirty canonical rows" in errors


def test_grammar_stdlib_t30_v3_rejects_unbound_human_review_receipt(tmp_path) -> None:
    _write_t30_v3_complete_phase_fixture(tmp_path)
    adjudication_path = tmp_path / "manifests/grammar-stdlib-accuracy-t30-adjudication-v3.json"
    adjudication = json.loads(adjudication_path.read_text(encoding="utf-8"))
    adjudication["review_receipt_sha256"] = "NOT_A_HASH_OR_RECEIPT"
    adjudication_path.write_text(json.dumps(adjudication), encoding="utf-8")
    _rewrite_canonical_self_hash(adjudication_path, "adjudication_sha256")

    errors = validate_grammar_stdlib_t30_successor_contract(tmp_path)

    assert "T30-v3 human review receipt identity or adjudication linkage contains drift" in errors


def test_artifact_store_policy_is_ratified_and_budgeted() -> None:
    root = repository_root()
    policy = load_json(root / "manifests/artifact-store-policy.json")

    assert validate_artifact_store_policy_contract(root) == []
    assert policy["scope"] == "local_only_no_distribution"
    assert policy["budget"]["per_run_cap_bytes"] == 40 * 1024**3
    assert policy["retention"]["published_artifact_automatic_deletion"] is False


def test_artifact_store_policy_rejects_an_unfunded_reserve(tmp_path) -> None:
    root = repository_root()
    policy = deepcopy(load_json(root / "manifests/artifact-store-policy.json"))
    policy["measurement"]["filesystem_available_bytes"] = 80 * 1024**3

    destination = tmp_path / "manifests"
    destination.mkdir(parents=True)
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    shutil.copy2(root / "manifests/decision-register.json", destination)
    (destination / "artifact-store-policy.json").write_text(json.dumps(policy), encoding="utf-8")

    errors = validate_artifact_store_policy_contract(tmp_path)
    assert "artifact-store observation does not meet minimum pre-run free space" in errors
    assert "artifact-store budget cannot preserve its required post-run reserve" in errors


def test_hyperparameter_grid_is_pre_registered_bounded_and_ratified() -> None:
    root = repository_root()
    grid = load_json(root / "manifests/hyperparameter-grid.json")

    assert validate_hyperparameter_grid_contract(root) == []
    assert grid["registered_before_w5_candidate_results"] is True
    assert len(grid["screening"]["configurations"]) == 4
    assert grid["finalist_repeats"]["seeds"] == [17, 29, 43]
    assert grid["budget"]["max_total_optimizer_steps"] == 700


def test_hyperparameter_grid_rejects_cartesian_and_budget_drift(tmp_path) -> None:
    root = repository_root()
    shutil.copytree(root / "manifests", tmp_path / "manifests")
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    path = tmp_path / "manifests/hyperparameter-grid.json"
    grid = json.loads(path.read_text(encoding="utf-8"))
    grid["screening"]["configurations"][3] = deepcopy(grid["screening"]["configurations"][2])
    grid["budget"]["max_total_optimizer_steps"] = 701
    path.write_text(json.dumps(grid), encoding="utf-8")

    errors = validate_hyperparameter_grid_contract(tmp_path)

    assert "W5 grid must be the exact four-configuration rank/LR Cartesian set" in errors
    assert "W5 total step budget is inconsistent" in errors


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("fixed", "lora_dropout", 0.1),
        ("fixed", "max_seq_length", 2048),
    ],
)
def test_hyperparameter_grid_schema_rejects_unqualified_fixed_settings(
    tmp_path, section, field, value
) -> None:
    root = repository_root()
    shutil.copytree(root / "manifests", tmp_path / "manifests")
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    path = tmp_path / "manifests/hyperparameter-grid.json"
    grid = json.loads(path.read_text(encoding="utf-8"))
    grid[section][field] = value
    path.write_text(json.dumps(grid), encoding="utf-8")

    errors = validate_hyperparameter_grid_contract(tmp_path)

    assert errors
    assert any(field in error for error in errors)


@pytest.mark.parametrize("field", ["stop_rules", "non_claims"])
def test_hyperparameter_grid_schema_pins_stop_and_nonclaim_policy(tmp_path, field) -> None:
    root = repository_root()
    shutil.copytree(root / "manifests", tmp_path / "manifests")
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    path = tmp_path / "manifests/hyperparameter-grid.json"
    grid = json.loads(path.read_text(encoding="utf-8"))
    grid[field][0] = "policy_drift"
    path.write_text(json.dumps(grid), encoding="utf-8")

    errors = validate_hyperparameter_grid_contract(tmp_path)

    assert errors
    assert any(field in error for error in errors)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("publication", "atomic_rename", False),
        ("retention", "published_artifact_automatic_deletion", True),
    ],
)
def test_artifact_store_schema_rejects_unsafe_publication_policy(
    tmp_path, section, field, value
) -> None:
    root = repository_root()
    shutil.copytree(root / "manifests", tmp_path / "manifests")
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    path = tmp_path / "manifests/artifact-store-policy.json"
    policy = json.loads(path.read_text(encoding="utf-8"))
    policy[section][field] = value
    path.write_text(json.dumps(policy), encoding="utf-8")

    errors = validate_artifact_store_policy_contract(tmp_path)

    assert errors
    assert any(field in error for error in errors)


def test_source_manifest_rejects_short_revision() -> None:
    root = repository_root()
    schema = load_json(root / "schemas/source-model-revisions.schema.json")
    manifest = deepcopy(load_json(root / "manifests/source-model-revisions.json"))
    manifest["source"]["revision"] = "abc123"

    errors = validate_instance(manifest, schema)

    assert any("revision" in error and "does not match" in error for error in errors)


def test_ratified_source_manifest_rejects_open_decisions() -> None:
    root = repository_root()
    schema = load_json(root / "schemas/source-model-revisions.schema.json")
    manifest = deepcopy(load_json(root / "manifests/source-model-revisions.json"))
    manifest["state"] = "ratified"
    manifest["source"]["language_version_status"] = "ratified"
    manifest["runtime"]["pinned_version"] = "0.6.15"
    manifest["runtime"]["status"] = "qualified"
    manifest["open_decision_refs"] = ["O-004"]

    errors = validate_instance(manifest, schema)

    assert any("open_decision_refs" in error and "empty" in error for error in errors)


def test_benchmark_contract_rejects_prohibited_sensitivity() -> None:
    root = repository_root()
    schema = load_json(root / "schemas/benchmark-task.schema.json")
    task = deepcopy(load_json(root / "examples/benchmark-task.draft.json"))
    task["provenance"]["sensitivity"] = "prohibited"

    errors = validate_instance(task, schema)

    assert any("prohibited" in error for error in errors)


def test_sealed_benchmark_task_requires_closed_oracles_and_ratified_language() -> None:
    root = repository_root()
    schema = load_json(root / "schemas/benchmark-task.schema.json")
    task = deepcopy(load_json(root / "examples/benchmark-task.draft.json"))
    task["status"] = "sealed"

    errors = validate_instance(task, schema)

    assert any("ratified" in error for error in errors)
    assert any("pending" in error for error in errors)


def test_sealed_source_task_rejects_semantic_waiver_without_structural_oracles() -> None:
    root = repository_root()
    schema = load_json(root / "schemas/benchmark-task.schema.json")
    task = deepcopy(load_json(root / "examples/benchmark-task.draft.json"))
    task["status"] = "sealed"
    task["metis"]["language_version_status"] = "ratified"
    task["oracles"] = [
        {
            "stage": "semantic",
            "expectation": "not_applicable",
            "evidence_ref": "waived",
        }
    ]

    errors = validate_instance(task, schema)

    assert errors
    assert any("does not contain" in error for error in errors)


def test_artifact_policy_rejects_payloads_and_secret_paths() -> None:
    errors = validate_artifact_policy_paths(
        [
            "README.md",
            "artifacts/adapter.bin",
            "models/base/model.safetensors",
            "nested/.env",
            "nested/.env.production",
            "checkpoints/optimizer.ckpt",
            "keys/signing.pem",
            "datasets/cache.parquet",
            "config/credentials.json",
            "qualification/train.jsonl",
            "qualification/process.log",
        ]
    )

    assert len(errors) == 13


def test_artifact_policy_rejects_binary_and_disguised_private_key(tmp_path) -> None:
    (tmp_path / "payload.dat").write_bytes(b"\x00\xff\x00")
    (tmp_path / "notes.txt").write_text(
        "-----BEGIN " + "PRIVATE KEY-----\nredacted-test-fixture\n",
        encoding="utf-8",
    )

    errors = validate_repository_file_contents(tmp_path, ["payload.dat", "notes.txt"])

    assert errors == [
        "binary repository file is forbidden: payload.dat",
        "private key material is forbidden: notes.txt",
    ]


def _copy_qualification_contract(tmp_path):
    root = repository_root()
    required = [
        "qualification/runtime-pin.json",
        "qualification/checkpoint-pin.json",
        "qualification/pyproject.toml",
        "qualification/train_full_state.py",
        "qualification/uv.lock",
        "manifests/source-model-revisions.json",
        "manifests/decision-register.json",
        "orchestra/runs/2026-08-20-w1-w4-entry/W4-QUALIFICATION.md",
    ]
    for relative in required:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination)
    return tmp_path


def test_qualification_contract_rejects_reopened_runtime(tmp_path) -> None:
    root = _copy_qualification_contract(tmp_path)
    runtime_path = root / "qualification/runtime-pin.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["status"] = "candidate_executed_environment"
    runtime["qualification_remaining"] = ["finite_backward"]
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")

    errors = validate_qualification_contract(root)

    assert "qualification runtime is not marked qualified" in errors
    assert "qualification runtime retains incomplete gates" in errors


def test_qualification_contract_rejects_resume_semantics_drift(tmp_path) -> None:
    root = _copy_qualification_contract(tmp_path)
    runtime_path = root / "qualification/runtime-pin.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["full_state_resume_semantics"] = (
        "local_wrapper_optimizer_rng_sampler_global_step_bit_exact_4_vs_2_plus_resume"
    )
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")

    errors = validate_qualification_contract(root)

    assert "qualification full-state resume semantics are missing or overstated" in errors


def test_qualification_contract_rejects_open_o004_reference(tmp_path) -> None:
    root = _copy_qualification_contract(tmp_path)
    manifest_path = root / "manifests/source-model-revisions.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["open_decision_refs"] = ["O-004"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors = validate_qualification_contract(root)

    assert "qualified source/model manifest retains open decision references" in errors
