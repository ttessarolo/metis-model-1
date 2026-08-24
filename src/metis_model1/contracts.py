from __future__ import annotations

import hashlib
import json
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from metis_model1 import catalog_maintenance_probe_evidence as probe_evidence
from metis_model1.evaluation import wilson_interval

CONTRACT_PAIRS = (
    ("schemas/source-model-revisions.schema.json", "manifests/source-model-revisions.json"),
    ("schemas/decision-register.schema.json", "manifests/decision-register.json"),
    ("schemas/benchmark-plan.schema.json", "manifests/benchmark-plan.json"),
    ("schemas/benchmark-task.schema.json", "examples/benchmark-task.draft.json"),
    ("schemas/accuracy-target.schema.json", "manifests/accuracy-target.json"),
    ("schemas/artifact-store-policy.schema.json", "manifests/artifact-store-policy.json"),
    ("schemas/dependency-closure.schema.json", "manifests/slice-30-closure.json"),
    ("schemas/source-asset-register.schema.json", "manifests/slice-30-assets.json"),
    ("schemas/dataset-example.schema.json", "examples/dataset-example.synthetic.json"),
    ("schemas/dataset-manifest.schema.json", "examples/dataset-manifest.synthetic.json"),
    ("schemas/split-manifest.schema.json", "examples/split-manifest.synthetic.json"),
    ("schemas/evaluation-report.schema.json", "examples/evaluation-report.synthetic.json"),
    ("schemas/hyperparameter-grid.schema.json", "manifests/hyperparameter-grid.json"),
    (
        "schemas/w1-slice-30-blocker-map.schema.json",
        "manifests/w1-slice-30-blocker-map-v1.json",
    ),
    (
        "schemas/w2-rights-dossier.schema.json",
        "manifests/w2-rights-dossier-v1.json",
    ),
    (
        "schemas/w1-slice-30-oracle-receipts.schema.json",
        "manifests/w1-slice-30-oracle-receipts-v1.json",
    ),
    (
        "schemas/w1-leakage-group-assignment.schema.json",
        "manifests/w1-leakage-group-assignment-v1.json",
    ),
    (
        "schemas/w1-held-out-family-map.schema.json",
        "manifests/w1-held-out-family-map-v1.json",
    ),
    ("schemas/w1-benchmark-seal.schema.json", "manifests/w1-benchmark-seal-v1.json"),
    (
        "schemas/catalog-maintenance-pin.schema.json",
        "manifests/catalog-maintenance-pin-v1.json",
    ),
    (
        "schemas/catalog-retrieval-execution-receipt.schema.json",
        "manifests/catalog-retrieval-execution-v1.json",
    ),
    (
        "schemas/catalog-maintenance-probe.schema.json",
        "manifests/catalog-maintenance-probe-v1.json",
    ),
    (
        "schemas/catalog-maintenance-probe-freeze.schema.json",
        "manifests/catalog-maintenance-probe-freeze-v1.json",
    ),
    (
        "schemas/catalog-maintenance-probe-evaluation.schema.json",
        "manifests/catalog-maintenance-probe-evaluation-v1.json",
    ),
    (
        "schemas/catalog-maintenance-probe-decision.schema.json",
        "manifests/catalog-maintenance-probe-decision-v1.json",
    ),
    (
        "schemas/catalog-maintenance-successor-probe.schema.json",
        "manifests/catalog-maintenance-successor-probe-v1.json",
    ),
    (
        "schemas/initial-local-qlora-plan.schema.json",
        "manifests/initial-local-qlora-plan-v1.json",
    ),
    ("schemas/accuracy-uplift-plan.schema.json", "manifests/accuracy-uplift-plan.json"),
)

STANDALONE_SCHEMAS = (
    "schemas/accuracy-maintenance-roster.schema.json",
    "schemas/catalog-retrieval-receipt.schema.json",
    "schemas/catalog-maintenance-successor-freeze.schema.json",
    "schemas/catalog-maintenance-successor-evaluation.schema.json",
    "schemas/catalog-maintenance-successor-decision.schema.json",
    "schemas/f5-migration-fixture.schema.json",
    "schemas/f5-migration-result.schema.json",
    "schemas/f6-blind-review-request.schema.json",
    "schemas/f6-human-review-final.schema.json",
    "schemas/f6-human-review-policy.schema.json",
    "schemas/f6-human-review-receipt.schema.json",
    "schemas/f6-structural-auto-result.schema.json",
    "schemas/f6-structural-truth.schema.json",
    "schemas/maintenance-decision.schema.json",
    "schemas/w3-bridge-replay.schema.json",
    "schemas/w3-native-loader-evidence.schema.json",
    "schemas/w3-production-authority.schema.json",
    "schemas/w3-qualification.schema.json",
    "schemas/w3-semantic-spec.schema.json",
    "schemas/w3-source-register.schema.json",
    "schemas/w3-run.schema.json",
)

REQUIRED_FOUNDATION_PATHS = (
    "AGENTS.md",
    "BLACKBOARD.md",
    "Makefile",
    "pyproject.toml",
    "uv.lock",
    "src/metis_model1/w3_builder.py",
    "src/metis_model1/w3_oracles.py",
    "src/metis_model1/w3_production_adapter.py",
    "src/metis_model1/w1_blockers.py",
    "src/metis_model1/w1_seal.py",
    "src/metis_model1/w2_rights.py",
    "src/metis_model1/f5_migration.py",
    "src/metis_model1/f6_human_review.py",
    "src/metis_model1/f6_structural.py",
    "src/metis_model1/accuracy_maintenance.py",
    "src/metis_model1/catalog_maintenance_pin.py",
    "src/metis_model1/catalog_retrieval.py",
    "src/metis_model1/catalog_retrieval_refresh.py",
    "src/metis_model1/catalog_maintenance_probe.py",
    "src/metis_model1/catalog_maintenance_probe_evidence.py",
    "src/metis_model1/catalog_maintenance_successor.py",
    "src/metis_model1/catalog_maintenance_successor_evidence.py",
    "src/metis_model1/maintenance_decision.py",
    "runtime/w3_qualifier.py",
    "runtime/w3_production_worker.py",
    "runtime/w3_bridge_gate.py",
    "docs/08-orchestration-and-blackboards.md",
    "docs/09-repository-and-artifact-policy.md",
    "docs/10-open-decisions.md",
    "docs/11-feasibility-and-risks.md",
    "docs/12-accuracy-99-execution-plan.md",
    "docs/16-accuracy-wave-catalog-domain-maintenance.md",
    "docs/17-catalog-prompt-cure-successor.md",
    "docs/18-initial-local-qlora.md",
    ".orchestra/teams.json",
    "manifests/accuracy-target.json",
    "manifests/artifact-store-policy.json",
    "manifests/hyperparameter-grid.json",
    "manifests/slice-30-assets.json",
    "manifests/slice-30-closure.json",
    "manifests/source-model-revisions.json",
    "manifests/decision-register.json",
    "manifests/benchmark-plan.json",
    "manifests/w3-f1-f3-smoke-candidates.json",
    "manifests/w3-f1-f3-smoke-semantic-specs.json",
    "manifests/w1-slice-30-blocker-map-v1.json",
    "manifests/w2-rights-dossier-v1.json",
    "manifests/w1-slice-30-oracle-receipts-v1.json",
    "manifests/w1-leakage-group-assignment-v1.json",
    "manifests/w1-held-out-family-map-v1.json",
    "manifests/w1-benchmark-seal-v1.json",
    "manifests/catalog-maintenance-pin-v1.json",
    "manifests/catalog-retrieval-execution-v1.json",
    "manifests/catalog-retrieval-public-synthetic-v1.json",
    "manifests/catalog-maintenance-probe-v1.json",
    "manifests/catalog-maintenance-probe-freeze-v1.json",
    "manifests/catalog-maintenance-probe-evaluation-v1.json",
    "manifests/catalog-maintenance-probe-decision-v1.json",
    "manifests/accuracy-uplift-plan.json",
    "schemas/catalog-maintenance-probe.schema.json",
    "schemas/catalog-maintenance-probe-freeze.schema.json",
    "schemas/catalog-maintenance-probe-evaluation.schema.json",
    "schemas/catalog-maintenance-probe-decision.schema.json",
    "manifests/catalog-maintenance-successor-probe-v1.json",
    "manifests/initial-local-qlora-plan-v1.json",
    "manifests/initial-local-qlora-exclusions-v1.json",
    "schemas/catalog-maintenance-successor-probe.schema.json",
    "schemas/catalog-maintenance-successor-freeze.schema.json",
    "schemas/catalog-maintenance-successor-evaluation.schema.json",
    "schemas/catalog-maintenance-successor-decision.schema.json",
    "schemas/initial-local-qlora-plan.schema.json",
    "fixtures/catalog-maintenance/probe-v1/cases/author-enum3.json",
    "fixtures/catalog-maintenance/probe-v1/cases/author-open.json",
    "fixtures/catalog-maintenance/probe-v1/cases/author-inline-tiny.json",
    "fixtures/catalog-maintenance/probe-v1/cases/author-nested-enum2.json",
    "fixtures/catalog-maintenance/probe-v1/cases/edit-inline4-to-enum4.json",
    "fixtures/catalog-maintenance/probe-v1/cases/edit-invalid-open-inline.json",
    "fixtures/catalog-maintenance/probe-v1/cases/repair-unsynchronized-enum.json",
    "fixtures/catalog-maintenance/probe-v1/cases/author-retrieval-curated.json",
    "fixtures/catalog-maintenance/successor-v1/cases/author-audience-enum5.json",
    "fixtures/catalog-maintenance/successor-v1/cases/author-summary-open.json",
    "fixtures/catalog-maintenance/successor-v1/cases/author-availability-inline.json",
    "fixtures/catalog-maintenance/successor-v1/cases/author-nested-code-enum4.json",
    "fixtures/catalog-maintenance/successor-v1/cases/edit-category-inline3-to-enum3.json",
    "fixtures/catalog-maintenance/successor-v1/cases/edit-invalid-query-open.json",
    "fixtures/catalog-maintenance/successor-v1/cases/repair-tags-unsynchronized-enum3.json",
    "fixtures/catalog-maintenance/successor-v1/cases/edit-retrieval-curated-not-inline.json",
    "fixtures/catalog-maintenance/public-synthetic-v1/metis.toml",
    "fixtures/catalog-maintenance/public-synthetic-v1/catalogs/aa-video.metis",
    "fixtures/catalog-maintenance/public-synthetic-v1/catalogs/bb-people.metis",
    "fixtures/catalog-maintenance/public-synthetic-v1/values/aa-list.metis",
    "fixtures/catalog-maintenance/public-synthetic-v1/values/bb-reflected.metis",
    "fixtures/catalog-maintenance/public-synthetic-v1/values/cc-editorial.metis",
    "qualification/.python-version",
    "qualification/README.md",
    "qualification/checkpoint-pin.json",
    "qualification/compare_full_state.py",
    "qualification/generate_fixture.py",
    "qualification/generate_sequence_fixture.py",
    "qualification/probe_model.py",
    "qualification/pyproject.toml",
    "qualification/resummarize_telemetry.py",
    "qualification/run_with_telemetry.py",
    "qualification/runtime-pin.json",
    "qualification/test_full_state.py",
    "qualification/train_full_state.py",
    "qualification/uv.lock",
    "qualification/verify_adapter.py",
    "qualification/verify_checkpoint.py",
    "src/metis_model1/initial_local_qlora_dataset.py",
    "src/metis_model1/initial_local_qlora_runtime.py",
    "src/metis_model1/initial_local_qlora_b12.py",
    "src/metis_model1/initial_local_qlora_train.py",
    "orchestra/runs/2026-08-20-foundation/BLACKBOARD.md",
    "orchestra/runs/2026-08-20-foundation/SESSIONS.md",
    "orchestra/runs/2026-08-20-w1-w4-entry/BLACKBOARD.md",
    "orchestra/runs/2026-08-20-w1-w4-entry/SESSIONS.md",
    "orchestra/runs/2026-08-20-w1-w4-entry/W4-QUALIFICATION.md",
    "orchestra/runs/2026-08-20-accuracy-99-pilot/BLACKBOARD.md",
    "orchestra/runs/2026-08-20-accuracy-99-pilot/SESSIONS.md",
    "orchestra/runs/2026-08-20-accuracy-99-pilot/KIMI-ACCURACY99-AUDIT.md",
    "orchestra/runs/2026-08-20-accuracy-99-pilot/W1-STRUCTURAL-PATH.md",
    "orchestra/runs/2026-08-20-accuracy-99-pilot/W4-SEQUENCE-1024-EXPANSION.md",
    "schemas/accuracy-target.schema.json",
    "schemas/artifact-store-policy.schema.json",
    "schemas/dataset-example.schema.json",
    "schemas/dataset-manifest.schema.json",
    "schemas/dependency-closure.schema.json",
    "schemas/evaluation-report.schema.json",
    "schemas/hyperparameter-grid.schema.json",
    "schemas/source-asset-register.schema.json",
    "schemas/split-manifest.schema.json",
    "schemas/source-model-revisions.schema.json",
    "schemas/decision-register.schema.json",
    "schemas/benchmark-plan.schema.json",
    "schemas/benchmark-task.schema.json",
    "schemas/w3-qualification.schema.json",
    "schemas/w3-production-authority.schema.json",
    "schemas/w3-bridge-replay.schema.json",
    "schemas/w3-native-loader-evidence.schema.json",
    "schemas/w3-semantic-spec.schema.json",
    "schemas/w3-source-register.schema.json",
    "schemas/w3-run.schema.json",
    "schemas/w1-slice-30-blocker-map.schema.json",
    "schemas/w2-rights-dossier.schema.json",
    "schemas/w1-slice-30-oracle-receipts.schema.json",
    "schemas/w1-leakage-group-assignment.schema.json",
    "schemas/w1-held-out-family-map.schema.json",
    "schemas/w1-benchmark-seal.schema.json",
    "schemas/accuracy-maintenance-roster.schema.json",
    "schemas/catalog-maintenance-pin.schema.json",
    "schemas/catalog-retrieval-execution-receipt.schema.json",
    "schemas/catalog-maintenance-probe.schema.json",
    "schemas/catalog-maintenance-probe-freeze.schema.json",
    "schemas/catalog-retrieval-receipt.schema.json",
    "schemas/accuracy-uplift-plan.schema.json",
    "schemas/f5-migration-fixture.schema.json",
    "schemas/f5-migration-result.schema.json",
    "schemas/f6-blind-review-request.schema.json",
    "schemas/f6-human-review-final.schema.json",
    "schemas/f6-human-review-policy.schema.json",
    "schemas/f6-human-review-receipt.schema.json",
    "schemas/f6-structural-auto-result.schema.json",
    "schemas/f6-structural-truth.schema.json",
    "schemas/maintenance-decision.schema.json",
    "tests/test_w3_production_adapter.py",
    "tests/test_w3_qualifier.py",
    "tests/test_w3_production_worker.py",
    "tests/test_w3_bridge_gate.py",
    "tests/test_w1_blockers.py",
    "tests/test_w1_seal.py",
    "tests/test_w2_rights.py",
    "tests/test_accuracy_maintenance.py",
    "tests/test_catalog_maintenance_pin.py",
    "tests/test_catalog_retrieval.py",
    "tests/test_catalog_retrieval_refresh.py",
    "tests/test_catalog_maintenance_probe_manifest.py",
    "tests/test_catalog_maintenance_probe.py",
    "tests/test_catalog_maintenance_probe_evidence.py",
    "tests/test_accuracy_uplift_plan.py",
    "tests/test_f5_migration.py",
    "tests/test_f6_human_review.py",
    "tests/test_f6_structural.py",
    "tests/test_maintenance_decision.py",
    "tests/test_initial_local_qlora_contract.py",
    "tests/test_initial_local_qlora_dataset.py",
    "tests/test_initial_local_qlora_runtime.py",
    "tests/test_initial_local_qlora_b12.py",
    "tests/test_initial_local_qlora_train.py",
)

FORBIDDEN_REPOSITORY_PREFIXES = (
    "artifacts/",
    "checkpoints/",
    "datasets/materialized/",
    "models/",
    "runs/raw/",
)
FORBIDDEN_MODEL_SUFFIXES = (
    ".bin",
    ".ckpt",
    ".gguf",
    ".mlmodel",
    ".npz",
    ".onnx",
    ".pt",
    ".pth",
    ".safetensors",
)
FORBIDDEN_DATA_SUFFIXES = (".arrow", ".jsonl", ".log", ".parquet", ".sqlite")
FORBIDDEN_SECRET_SUFFIXES = (".key", ".p12", ".pem", ".pfx")
FORBIDDEN_SECRET_NAMES = ("credentials.json", "secrets.json", "service-account.json")
MAX_REPOSITORY_FILE_BYTES = 5 * 1024 * 1024
PRIVATE_KEY_MARKERS = tuple(
    "-----BEGIN " + key_type + "PRIVATE KEY-----" for key_type in ("", "RSA ", "EC ", "OPENSSH ")
)


@dataclass
class ValidationReport:
    passes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    open_by_wave: dict[str, list[str]] = field(default_factory=dict)
    open_nonblocking: list[str] = field(default_factory=list)
    repository_files: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_instance(instance: Any, schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))
    rendered: list[str] = []
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        rendered.append(f"{location}: {error.message}")
    return rendered


def validate_cross_contracts(root: Path) -> list[str]:
    source_manifest = load_json(root / "manifests/source-model-revisions.json")
    register = load_json(root / "manifests/decision-register.json")
    decision_ids = [decision["id"] for decision in register["open_decisions"]]
    status_by_id = {decision["id"]: decision["status"] for decision in register["open_decisions"]}
    known = set(status_by_id)
    referenced = set(source_manifest["open_decision_refs"])
    missing = sorted(referenced - known)
    errors = [
        f"source manifest references unknown decision {decision_id}" for decision_id in missing
    ]
    if len(decision_ids) != len(known):
        errors.append("decision register contains duplicate decision IDs")
    for decision_id in sorted(referenced & known):
        if status_by_id[decision_id] != "open":
            errors.append(f"open_decision_refs contains non-open decision {decision_id}")

    if source_manifest["state"] == "ratified" and referenced:
        errors.append("ratified source manifest cannot retain open_decision_refs")

    model_roles = [model["role"] for model in source_manifest["models"]]
    if sorted(model_roles) != ["base_model", "mlx_checkpoint"]:
        errors.append("source manifest must contain exactly one base_model and one mlx_checkpoint")

    runtime_decision = source_manifest["runtime"]["decision_id"]
    runtime_status = source_manifest["runtime"]["status"]
    if runtime_status == "open" and runtime_decision not in referenced:
        errors.append(f"runtime decision {runtime_decision} is missing from open_decision_refs")
    if runtime_status != "open" and runtime_decision in referenced:
        errors.append(f"resolved runtime decision {runtime_decision} remains open in the manifest")
    return errors


def validate_benchmark_plan_contract(root: Path) -> list[str]:
    plan = load_json(root / "manifests/benchmark-plan.json")
    source_manifest = load_json(root / "manifests/source-model-revisions.json")
    errors: list[str] = []

    expected_families = {f"F-{number}" for number in range(1, 7)}
    family_by_id = {family["id"]: family for family in plan["families"]}
    if set(family_by_id) != expected_families or len(plan["families"]) != 6:
        errors.append("benchmark plan must contain each family F-1 through F-6 exactly once")

    tasks = plan["slice_30"]["tasks"]
    task_ids = [task["task_id"] for task in tasks]
    source_paths = [task["source_path"] for task in tasks]
    blob_oids = [task["source_blob_oid"] for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        errors.append("benchmark slice contains duplicate task IDs")
    if len(source_paths) != len(set(source_paths)):
        errors.append("benchmark slice contains duplicate source paths")
    if len(blob_oids) != len(set(blob_oids)):
        errors.append("benchmark slice contains duplicate source blob OIDs")

    for family_id in sorted(expected_families):
        family = family_by_id.get(family_id)
        if family is None:
            continue
        allocations = [task for task in tasks if task["family"] == family_id]
        if len(allocations) != family["allocated_tasks"]:
            errors.append(
                f"benchmark family {family_id} allocates {len(allocations)} tasks, "
                f"expected {family['allocated_tasks']}"
            )
        for task in allocations:
            if task["mode"] != family["mode"]:
                errors.append(f"benchmark task {task['task_id']} has a family/mode mismatch")
            missing_oracles = set(family["required_oracles"]) - set(task["intended_oracles"])
            if missing_oracles:
                errors.append(
                    f"benchmark task {task['task_id']} is missing intended oracles "
                    f"{','.join(sorted(missing_oracles))}"
                )

    if plan["source_revision"] != source_manifest["source"]["revision"]:
        errors.append("benchmark plan and source manifest revisions differ")
    if plan["language_version"] != source_manifest["source"]["language_version"]:
        errors.append("benchmark plan and source manifest language versions differ")
    return errors


def validate_accuracy_target_contract(root: Path) -> list[str]:
    target = load_json(root / "manifests/accuracy-target.json")
    errors: list[str] = []

    family_counts = target["family_counts"]
    if sum(family_counts.values()) != target["total"]:
        errors.append("accuracy target family counts do not sum to the total denominator")

    required_predicates = {
        "request_fulfilled_or_correctly_refused_when_impossible_or_underspecified",
        "all_applicable_parse_link_validate_compile_oracles_pass",
        "semantic_or_blind_human_oracle_passes",
        "unrelated_regions_are_preserved_and_patch_minimality_passes_when_applicable",
        "no_invented_identifier_is_accepted_as_valid",
        "result_is_produced_within_two_repair_cycles",
        "tool_or_budget_failure_counts_as_task_failure",
    }
    if set(target["success_requires"]) != required_predicates:
        errors.append("accuracy target success predicate is incomplete or contains drift")

    required_vetoes = {
        "accepted_invented_identifier",
        "benchmark_leakage",
        "identity_mismatch",
        "prohibited_data_exposure",
        "semantic_wrong_compile_clean_accepted",
        "unauthorized_metis_write",
        "unrelated_destructive_change",
    }
    if set(target["forbidden_critical_failures"]) != required_vetoes:
        errors.append("accuracy target critical-failure veto set contains drift")

    total = target["total"]
    maximum_failures = target["maximum_failures"]
    confidence = target["confidence"]
    lower_min = target["wilson_lower_min"]
    supported_lower = wilson_interval(total - maximum_failures, total, confidence)[0]
    next_failure_lower = wilson_interval(total - maximum_failures - 1, total, confidence)[0]
    if supported_lower < lower_min:
        errors.append("accuracy target denominator cannot support its Wilson lower-bound claim")
    if next_failure_lower >= lower_min:
        errors.append(
            "accuracy target denominator no longer enforces its recorded maximum-failure gate"
        )

    minimum_for_failure_budget = next(
        denominator
        for denominator in range(maximum_failures + 1, total + 1)
        if wilson_interval(denominator - maximum_failures, denominator, confidence)[0] >= lower_min
    )
    if target["minimum_distinct_leakage_groups"] != minimum_for_failure_budget:
        errors.append("accuracy target independent-group minimum differs from Wilson arithmetic")
    if target["minimum_distinct_leakage_groups"] > total:
        errors.append("accuracy target requires more leakage groups than tasks")
    return errors


def _validate_standalone_contract_schema(
    root: Path, schema_path: str, instance_path: str
) -> tuple[Any, list[str]]:
    """Load and validate a standalone contract before reading semantic fields."""

    instance = load_json(root / instance_path)
    schema = load_json(root / schema_path)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        return instance, [f"invalid schema {schema_path}: {error.message}"]
    schema_errors = validate_instance(instance, schema)
    if schema_errors:
        return instance, [f"{instance_path}: {error}" for error in schema_errors]
    return instance, []


def validate_artifact_store_policy_contract(root: Path) -> list[str]:
    policy, schema_errors = _validate_standalone_contract_schema(
        root,
        "schemas/artifact-store-policy.schema.json",
        "manifests/artifact-store-policy.json",
    )
    # Const mutations preserve the object shape, so retain the historical
    # semantic diagnostics as well as the schema error.  Structural/type
    # failures cannot be safely inspected by the semantic pass.
    if schema_errors and any(not error.endswith(" was expected") for error in schema_errors):
        return schema_errors
    measurement = policy["measurement"]
    budget = policy["budget"]
    errors: list[str] = list(schema_errors)

    available = measurement["filesystem_available_bytes"]
    per_run_cap = budget["per_run_cap_bytes"]
    if available < budget["minimum_free_before_run_bytes"]:
        errors.append("artifact-store observation does not meet minimum pre-run free space")
    if available - per_run_cap < budget["minimum_free_after_reserved_run_bytes"]:
        errors.append("artifact-store budget cannot preserve its required post-run reserve")
    if (
        measurement["observed_full_state_checkpoint_bytes"]
        * budget["max_published_checkpoints_per_configuration"]
        >= per_run_cap
    ):
        errors.append("artifact-store checkpoint allowance exhausts the per-run budget")
    if measurement["existing_artifact_bytes"] >= available:
        errors.append("artifact-store measurement is internally inconsistent")

    expected_directories = {
        "input_refs",
        "configs",
        "checkpoints",
        "telemetry",
        "reports",
    }
    if set(policy["layout"]["required_directories"]) != expected_directories:
        errors.append("artifact-store required directory set contains drift")
    expected_identities = {
        "source_revision",
        "compiler_identity",
        "runtime_hash",
        "base_model_hash",
        "dataset_hash",
        "split_manifest_hash",
        "config_hash",
        "prompt_roster_hash",
        "oracle_contract_hash",
        "adapter_hash",
    }
    if set(policy["identity_fields"]) != expected_identities:
        errors.append("artifact-store immutable identity field set contains drift")
    if not policy["artifact_root"].startswith("artifacts/"):
        errors.append("artifact-store root must remain under the ignored local artifact boundary")

    register = load_json(root / "manifests/decision-register.json")
    decision = next(
        (item for item in register["open_decisions"] if item["id"] == "O-006"),
        None,
    )
    if (
        decision is None
        or decision["status"] != "ratified"
        or decision["blocks"]
        or not decision["resolution"]
    ):
        errors.append("O-006 is not fully ratified in the decision register")
    return errors


def validate_w5_xs_plan_contract(root: Path) -> list[str]:
    """Validate the plan-only W5-XS gate without touching model payloads."""

    try:
        plan, schema_errors = _validate_standalone_contract_schema(
            root,
            "schemas/w5-xs-plan.schema.json",
            "manifests/w5-xs-plan.json",
        )
        if schema_errors:
            return schema_errors

        errors: list[str] = []
        register = load_json(root / "manifests/decision-register.json")
        decisions = [item for item in register["open_decisions"] if item.get("id") == "O-011"]
        if (
            len(decisions) != 1
            or decisions[0].get("status") != "ratified"
            or decisions[0].get("blocks") != []
            or not decisions[0].get("resolution")
        ):
            errors.append("O-011 is not uniquely and fully ratified")

        spec = plan["canonical_spec"]
        spec_path = root / spec["path"]
        spec_hash = "sha256:" + hashlib.sha256(spec_path.read_bytes()).hexdigest()
        if spec_hash != spec["sha256"]:
            errors.append("W5-XS canonical specification hash contains drift")

        baseline = plan["baseline"]
        if sum(baseline["diagnostic_family_counts"].values()) != baseline["diagnostic_task_count"]:
            errors.append("W5-XS diagnostic family counts do not sum to 12")
        if (
            baseline["reusable_fixture_tasks"] + baseline["additional_task_specs_required"]
            != baseline["diagnostic_task_count"]
        ):
            errors.append("W5-XS reusable and additional task counts do not sum to 12")
        if sum(baseline["paired_family_counts"].values()) != baseline["paired_task_count"]:
            errors.append("W5-XS paired family counts do not sum to 24")

        dataset = plan["dataset"]
        if dataset["train_examples"] + dataset["dev_examples"] != dataset["total_examples"]:
            errors.append("W5-XS dataset counts do not sum to the fixed total")
        if (
            dataset["failure_driven_train_examples"] + dataset["canonical_replay_train_examples"]
            != dataset["train_examples"]
        ):
            errors.append("W5-XS train composition does not sum to the fixed train total")
        if (
            dataset["failure_driven_min_parent_template_groups"]
            * dataset["max_derivations_per_parent_template_group"]
            < dataset["failure_driven_train_examples"]
        ):
            errors.append("W5-XS failure-driven diversity cannot cover the train denominator")

        accuracy_target = load_json(root / "manifests/accuracy-target.json")
        accuracy_errors = validate_accuracy_target_contract(root)
        errors.extend(f"critical-failure roster: {error}" for error in accuracy_errors)
        if (
            baseline["require_zero_unlisted_critical_failures"]
            != accuracy_target["require_zero_unlisted_critical_failures"]
        ):
            errors.append("W5-XS unlisted critical-failure policy differs from its target")

        qualification_errors = validate_qualification_contract(root)
        errors.extend(f"qualification: {error}" for error in qualification_errors)
        publication_errors = validate_artifact_store_policy_contract(root)
        errors.extend(f"publication policy: {error}" for error in publication_errors)

        repository_files = git_repository_files(root)
        boundary_errors = validate_artifact_policy_paths(repository_files)
        boundary_errors.extend(validate_repository_file_contents(root, repository_files))
        errors.extend(f"repository boundary: {error}" for error in boundary_errors)
        return errors
    except Exception as error:  # noqa: BLE001 - the plan gate must fail closed
        return [f"W5-XS plan contract unreadable: {type(error).__name__}: {error}"]


def validate_catalog_maintenance_probe_contract(root: Path) -> list[str]:
    """Validate the immutable, public-synthetic probe specification only.

    This gate intentionally validates no model outputs and cannot create a
    pre-output seal.  The separate Git seal/evaluation authority remains
    fail-closed until an explicitly authorized wave wires it.
    """

    try:
        manifest_path = root / "manifests/catalog-maintenance-probe-v1.json"
        schema_path = root / "schemas/catalog-maintenance-probe.schema.json"
        manifest = load_json(manifest_path)
        schema = load_json(schema_path)
        errors = validate_instance(manifest, schema)
        if errors:
            return [f"catalog maintenance probe schema: {error}" for error in errors]

        def digest(payload: bytes) -> str:
            return "sha256:" + hashlib.sha256(payload).hexdigest()

        body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        canonical = json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if manifest["manifest_sha256"] != digest(canonical):
            errors.append("catalog maintenance probe manifest hash contains drift")

        expected_paths = {item["path"] for item in manifest["files"]}
        actual_paths = {
            path.relative_to(root).as_posix()
            for path in (root / "fixtures/catalog-maintenance/probe-v1").rglob("*")
            if path.is_file()
        }
        if actual_paths != expected_paths:
            errors.append("catalog maintenance probe case roster differs from manifest files")

        case_schema = schema["$defs"]["case"]
        cases: dict[str, dict[str, Any]] = {}
        for record in manifest["files"]:
            path = root / record["path"]
            if digest(path.read_bytes()) != record["sha256"]:
                errors.append(f"catalog maintenance probe case hash drift: {record['path']}")
            case = load_json(path)
            case_errors = validate_instance(case, case_schema)
            errors.extend(
                f"catalog maintenance probe case {record['path']}: {error}" for error in case_errors
            )
            case_id = case.get("case_id")
            if case_id in cases:
                errors.append(f"catalog maintenance probe duplicate case ID: {case_id}")
            cases[case_id] = case

        bindings = manifest["cases"]
        if len(bindings) != manifest["counts"]["cases"] or len(cases) != 8:
            errors.append("catalog maintenance probe must contain exactly 8 cases")
        if {binding["case_id"] for binding in bindings} != set(cases):
            errors.append("catalog maintenance probe case bindings do not match case files")
        if len({binding["root_id"] for binding in bindings}) != 8:
            errors.append("catalog maintenance probe roots are not distinct")
        if len({binding["template_id"] for binding in bindings}) != 8:
            errors.append("catalog maintenance probe templates are not distinct")
        if {case["provenance"]["lineage_component"] for case in cases.values()} != {
            "public-synthetic-catalog-v1"
        }:
            errors.append("catalog maintenance probe lineage is outside public synthetic scope")
        mode_counts = {
            "author": sum(case["mode"] == "author" for case in cases.values()),
            "edit": sum(case["mode"] == "edit" for case in cases.values()),
            "repair": sum(case["mode"] == "repair" for case in cases.values()),
        }
        declared_counts = {
            "authors": manifest["counts"]["authors"],
            "edits": manifest["counts"]["edits"],
            "repairs": manifest["counts"]["repairs"],
        }
        if mode_counts != {
            "author": declared_counts["authors"],
            "edit": declared_counts["edits"],
            "repair": declared_counts["repairs"],
        }:
            errors.append("catalog maintenance probe mode counts are not recomputed from cases")
        if manifest["status"] != "static_pre_output_specification":
            errors.append("catalog maintenance probe spec is not pre-output only")
        if manifest["gates"]["model_outputs_before_seal"] is not False:
            errors.append("catalog maintenance probe permits model output before its seal")
        return errors
    except Exception as error:  # noqa: BLE001 - the gate must fail closed
        return [f"catalog maintenance probe unreadable: {type(error).__name__}: {error}"]


def validate_catalog_maintenance_successor_contract(root: Path) -> list[str]:
    """Validate the fresh prompt-cure roster without granting output authority."""

    try:
        from metis_model1 import catalog_maintenance_successor as successor

        manifest, _schema, cases = successor.load_probe_contract(root)
        errors: list[str] = []
        expected_paths = {item["path"] for item in manifest["files"]}
        actual_paths = {
            path.relative_to(root).as_posix()
            for path in (root / "fixtures/catalog-maintenance/successor-v1").rglob("*")
            if path.is_file()
        }
        if actual_paths != expected_paths:
            errors.append("catalog maintenance successor case tree differs from its manifest")

        bindings = manifest["cases"]
        case_ids = [case["case_id"] for case in cases]
        roots = [case["provenance"]["semantic_root"] for case in cases]
        templates = [case["provenance"]["template_id"] for case in cases]
        if (
            len(cases) != 8
            or len(set(case_ids)) != 8
            or len(set(roots)) != 8
            or len(set(templates)) != 8
            or manifest["counts"]["gaps"] != 0
        ):
            errors.append("catalog maintenance successor roster is not 8/8/distinct/gaps0")
        if [binding["case_id"] for binding in bindings] != case_ids:
            errors.append("catalog maintenance successor binding order differs from cases")
        modes = {
            "authors": sum(case["mode"] == "author" for case in cases),
            "edits": sum(case["mode"] == "edit" for case in cases),
            "repairs": sum(case["mode"] == "repair" for case in cases),
        }
        if any(manifest["counts"][key] != value for key, value in modes.items()):
            errors.append("catalog maintenance successor mode arithmetic contains drift")
        if {case["provenance"]["lineage_component"] for case in cases} != {
            "public-synthetic-catalog-successor-v1"
        }:
            errors.append("catalog maintenance successor lineage is outside public synthetic")

        old_manifest = load_json(root / "manifests/catalog-maintenance-probe-v1.json")
        old_cases = [load_json(root / item["fixture_path"]) for item in old_manifest["cases"]]
        if set(case_ids) & {case["case_id"] for case in old_cases}:
            errors.append("catalog maintenance successor reuses a v1 case ID")
        if set(roots) & {case["provenance"]["semantic_root"] for case in old_cases}:
            errors.append("catalog maintenance successor reuses a v1 semantic root")
        if set(templates) & {case["provenance"]["template_id"] for case in old_cases}:
            errors.append("catalog maintenance successor reuses a v1 template")
        if {case["target"]["expected_source"] for case in cases} & {
            case["target"]["expected_source"] for case in old_cases
        }:
            errors.append("catalog maintenance successor reuses a v1 expected source")

        for case in cases:
            retrieval = (
                {"value": "Curated", "size": 1}
                if case["retrieval"]["kind"] == "public_synthetic_value"
                else None
            )
            messages = successor.build_messages(case, retrieval)
            rendered = "\n".join(message["content"] for message in messages)
            if [message["role"] for message in messages] != ["system", "user"]:
                errors.append(f"catalog maintenance successor role drift: {case['case_id']}")
            if case["target"]["expected_source"].strip() in rendered:
                errors.append(f"catalog maintenance successor target leakage: {case['case_id']}")
            feedback = successor.build_repair_message("catalog describe rejected candidate")
            if any(fragment in feedback for fragment in case["target"]["required_fragments"]):
                errors.append(f"catalog maintenance successor feedback leakage: {case['case_id']}")

        gates = manifest["gates"]
        if (
            gates["model_outputs_before_seal"] is not False
            or gates["training_authority"] is not False
            or gates["promotion_claim"] is not False
            or gates["accuracy_claim"] is not False
        ):
            errors.append("catalog maintenance successor grants forbidden authority")
        return errors
    except Exception as error:  # noqa: BLE001 - the gate must fail closed
        return [f"catalog maintenance successor unreadable: {type(error).__name__}: {error}"]


def validate_catalog_maintenance_successor_evidence_contract(root: Path) -> list[str]:
    """Validate either the lawful pre-output phase or both terminal receipts."""

    evaluation_path = root / "manifests/catalog-maintenance-successor-evaluation-v1.json"
    decision_path = root / "manifests/catalog-maintenance-successor-decision-v1.json"
    present = (evaluation_path.is_file(), decision_path.is_file())
    if present == (False, False):
        return []
    if present != (True, True):
        return ["catalog maintenance successor terminal evidence is only partially present"]
    try:
        from metis_model1 import catalog_maintenance_successor_evidence as evidence

        evaluation = load_json(evaluation_path)
        decision = load_json(decision_path)
        errors = [
            f"evaluation: {error}"
            for error in evidence.validate_evaluation_receipt(evaluation, root=root)
        ]
        errors.extend(
            f"decision: {error}"
            for error in evidence.validate_decision(
                decision, root=root, evaluation_path=evaluation_path
            )
        )
        return errors
    except Exception as error:  # noqa: BLE001 - fail closed on tracked evidence
        return [
            f"catalog maintenance successor evidence unreadable: {type(error).__name__}: {error}"
        ]


def validate_accuracy_uplift_plan_contract(root: Path) -> list[str]:
    """Validate the forward-only accuracy plan and its pending grammar boundary."""

    try:
        plan, schema_errors = _validate_standalone_contract_schema(
            root,
            "schemas/accuracy-uplift-plan.schema.json",
            "manifests/accuracy-uplift-plan.json",
        )
        if schema_errors:
            return schema_errors

        errors: list[str] = []
        probe_errors = validate_catalog_maintenance_probe_contract(root)
        errors.extend(probe_errors)
        probe = plan["catalog_maintenance_probe"]
        for name in ("manifest", "schema", "retrieval_manifest", "retrieval_receipt"):
            reference = probe[name]
            path = root / reference["path"]
            if not path.is_file():
                errors.append(f"catalog maintenance probe {name} reference is missing")
            elif "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
                errors.append(f"catalog maintenance probe {name} reference hash contains drift")
        probe_status = probe["status"]

        def validate_probe_seal(reference: Any) -> dict[str, Any] | None:
            if not isinstance(reference, dict):
                errors.append("evaluated catalog probe has no pre-output seal reference")
                return None
            seal_path = root / reference["path"]
            if not seal_path.is_file():
                errors.append("catalog probe pre-output seal is missing")
                return None
            seal_raw = seal_path.read_bytes()
            if "sha256:" + hashlib.sha256(seal_raw).hexdigest() != reference["sha256"]:
                errors.append("catalog probe pre-output seal raw hash contains drift")
            seal = load_json(seal_path)
            freeze_schema = load_json(root / "schemas/catalog-maintenance-probe-freeze.schema.json")
            errors.extend(
                f"catalog probe pre-output seal schema: {error}"
                for error in validate_instance(seal, freeze_schema)
            )
            seal_body = {key: value for key, value in seal.items() if key != "freeze_sha256"}
            seal_canonical = json.dumps(
                seal_body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if seal.get("freeze_sha256") != (
                "sha256:" + hashlib.sha256(seal_canonical).hexdigest()
            ):
                errors.append("catalog probe pre-output seal self-hash contains drift")
            if (
                seal.get("status") != "frozen_before_model_output"
                or seal.get("model_outputs_observed") is not False
                or seal.get("training_authorized") is not False
                or seal.get("counts")
                != {"cases_in": 8, "cases_out": 8, "cases_distinct": 8, "gaps": 0}
            ):
                errors.append("catalog probe pre-output seal is not fail-closed at 8/8")
            return seal

        if probe_status == "spec_ready":
            if (
                probe["pre_output_seal"] is not None
                or probe["evaluation_receipt"] is not None
                or probe["decision_report"] is not None
                or probe["model_outputs_observed"] is not False
            ):
                errors.append(
                    "catalog maintenance probe is not in its fail-closed spec-ready state"
                )
            if (
                plan["gates"]["catalog_probe_sealed_pre_output"]
                or plan["gates"]["catalog_probe_evaluation_allowed"]
            ):
                errors.append("catalog probe seal/evaluation gate opened before its verifier")
        elif probe_status == "sealed_pre_output":
            seal_reference = probe["pre_output_seal"]
            if not isinstance(seal_reference, dict):
                errors.append("sealed catalog probe has no pre-output seal reference")
            else:
                seal_path = root / seal_reference["path"]
                if not seal_path.is_file():
                    errors.append("catalog probe pre-output seal is missing")
                else:
                    seal_raw = seal_path.read_bytes()
                    if "sha256:" + hashlib.sha256(seal_raw).hexdigest() != seal_reference["sha256"]:
                        errors.append("catalog probe pre-output seal raw hash contains drift")
                    seal = load_json(seal_path)
                    freeze_schema = load_json(
                        root / "schemas/catalog-maintenance-probe-freeze.schema.json"
                    )
                    errors.extend(
                        f"catalog probe pre-output seal schema: {error}"
                        for error in validate_instance(seal, freeze_schema)
                    )
                    seal_body = {
                        key: value for key, value in seal.items() if key != "freeze_sha256"
                    }
                    seal_canonical = json.dumps(
                        seal_body,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    if (
                        seal.get("freeze_sha256")
                        != "sha256:" + hashlib.sha256(seal_canonical).hexdigest()
                    ):
                        errors.append("catalog probe pre-output seal self-hash contains drift")
                    if (
                        seal.get("status") != "frozen_before_model_output"
                        or seal.get("model_outputs_observed") is not False
                        or seal.get("training_authorized") is not False
                        or seal.get("counts")
                        != {"cases_in": 8, "cases_out": 8, "cases_distinct": 8, "gaps": 0}
                    ):
                        errors.append("catalog probe pre-output seal is not fail-closed at 8/8")
            if (
                probe["evaluation_receipt"] is not None
                or probe["decision_report"] is not None
                or probe["model_outputs_observed"] is not False
            ):
                errors.append("sealed catalog probe contains premature evaluation evidence")
            if not (
                plan["gates"]["catalog_probe_sealed_pre_output"]
                and plan["gates"]["catalog_probe_evaluation_allowed"]
            ):
                errors.append("sealed catalog probe did not open its bounded evaluation gate")
        elif probe_status == "evaluated":
            seal = validate_probe_seal(probe["pre_output_seal"])
            evidence_documents: dict[str, dict[str, Any]] = {}
            for name, expected_path in (
                (
                    "evaluation_receipt",
                    "manifests/catalog-maintenance-probe-evaluation-v1.json",
                ),
                (
                    "decision_report",
                    "manifests/catalog-maintenance-probe-decision-v1.json",
                ),
            ):
                reference = probe[name]
                if not isinstance(reference, dict) or reference.get("path") != expected_path:
                    errors.append(f"evaluated catalog probe {name} reference is not exact")
                    continue
                path = root / expected_path
                if not path.is_file():
                    errors.append(f"evaluated catalog probe {name} is missing")
                    continue
                raw = path.read_bytes()
                if "sha256:" + hashlib.sha256(raw).hexdigest() != reference["sha256"]:
                    errors.append(f"evaluated catalog probe {name} raw hash contains drift")
                evidence_documents[name] = load_json(path)
            evaluation = evidence_documents.get("evaluation_receipt")
            decision = evidence_documents.get("decision_report")
            if evaluation is not None:
                errors.extend(
                    f"catalog probe evaluation: {error}"
                    for error in probe_evidence.validate_evaluation_receipt(evaluation)
                )
                if (
                    evaluation.get("status") != "verified_local_cooperative"
                    or evaluation.get("counts")
                    != {
                        "cases_in": 8,
                        "cases_out": 8,
                        "cases_distinct": 8,
                        "gaps": 0,
                        "semantic_correct": 2,
                        "critical_failure": 6,
                        "invented_values": 0,
                        "legacy_inline": 0,
                        "retrieval_error": 6,
                        "skeleton_match": 2,
                    }
                    or evaluation.get("policy", {}).get("verdict") != "DIAGNOSE"
                    or evaluation.get("policy", {}).get("training_authorized") is not False
                ):
                    errors.append("catalog probe evaluation is not the exact 2/8 diagnostic")
                if seal is not None and evaluation.get("execution", {}).get(
                    "freeze_sha256"
                ) != seal.get("freeze_sha256"):
                    errors.append("catalog probe evaluation differs from its pre-output seal")
            if decision is not None:
                errors.extend(
                    f"catalog probe decision: {error}"
                    for error in probe_evidence.validate_decision(decision)
                )
                if (
                    decision.get("status") != "DIAGNOSE"
                    or decision.get("delta_qlora", {}).get("eligible") is not False
                    or decision.get("training_authorized") is not False
                    or decision.get("auto_qlora_authorized") is not False
                    or decision.get("promotion_claim") is not False
                    or decision.get("accuracy_claim") is not False
                ):
                    errors.append("catalog probe decision exceeds diagnostic-only authority")
            if probe["model_outputs_observed"] is not True:
                errors.append("evaluated catalog probe does not record observed model output")
            if not plan["gates"]["catalog_probe_sealed_pre_output"]:
                errors.append("evaluated catalog probe lost its pre-output seal gate")
            if plan["gates"]["catalog_probe_evaluation_allowed"]:
                errors.append("evaluated catalog probe still permits another model run")
        else:
            errors.append("catalog maintenance probe status is unknown")
        if probe["case_count"] != 8:
            errors.append("catalog maintenance probe case count is not 8")
        if (
            plan["catalog_value_domain"]["materialization_scope"]
            != "catalog_maintenance_probe_only"
        ):
            errors.append("catalog value-domain materialization scope is broader than the probe")
        register = load_json(root / "manifests/decision-register.json")
        decisions = [item for item in register["open_decisions"] if item.get("id") == "O-010"]
        if (
            len(decisions) != 1
            or decisions[0].get("status") != "ratified"
            or decisions[0].get("blocks") != []
            or not decisions[0].get("resolution")
        ):
            errors.append("O-010 is not uniquely and fully ratified")

        spec = plan["canonical_spec"]
        spec_path = root / spec["path"]
        spec_hash = "sha256:" + hashlib.sha256(spec_path.read_bytes()).hexdigest()
        if spec_hash != spec["sha256"]:
            errors.append("accuracy-uplift canonical specification hash contains drift")

        historical = plan["historical_evidence"]
        if historical["semantic_score"] != "11/12" or historical["source_oracle_audit"] != "12/12":
            errors.append(
                "historical B12 semantic score and source/oracle audit coverage are conflated"
            )

        wave = plan["wave"]
        expected_families = {f"F-{number}" for number in range(1, 7)}
        for split_name in ("diagnostic", "train", "dev", "final_test"):
            split = wave[split_name]
            counts = split["family_counts"]
            if set(counts) != expected_families:
                errors.append(f"accuracy-uplift {split_name} family roster is not F-1...F-6")
            if sum(counts.values()) != split["total"]:
                errors.append(f"accuracy-uplift {split_name} family counts do not sum to total")
        if wave["train"]["total"] + wave["dev"]["total"] != 80:
            errors.append("accuracy-uplift conditional dataset is not exactly 64+16")

        catalog = plan["catalog_value_domain"]
        reservations = catalog["coverage_reservation"]
        for split_name, wave_name in (("diagnostic", "diagnostic"), ("final_test", "final_test")):
            for family in ("F-1", "F-6"):
                reserved = reservations[split_name][family]
                if reserved < 1 or reserved > wave[wave_name]["family_counts"][family]:
                    errors.append(
                        f"catalog-domain {split_name} reservation for {family} is outside the split"
                    )

        upstream = plan["upstream_grammar_dependency"]
        gates = plan["gates"]
        pending = upstream["status"] == "awaiting_upstream_pin"
        surface_pending = upstream["status"] == "surface_pinned_implementation_pending"
        pinned = upstream["status"] == "pinned"
        surface_pinned = surface_pending or pinned
        if gates["surface_pin_complete"] != surface_pinned:
            errors.append("surface pin gate disagrees with the grammar dependency status")
        if gates["upstream_pin_complete"] != pinned:
            errors.append("upstream pin gate disagrees with the grammar dependency status")

        pending_forbidden = {
            "catalog_domain_prompt_truth",
            "catalog_domain_oracle_truth",
            "t30_model_outputs_before_complete_seal",
            "tenant_value_payloads",
            "training",
            "catalog_probe_model_outputs_before_probe_seal",
        }
        if pending:
            if upstream["pin"] is not None:
                errors.append("pending upstream grammar dependency must not carry a pin")
            if catalog["status"] != "reserved_pending_upstream_pin":
                errors.append("pending catalog-domain construct status was laundered")
            if catalog["materialization_allowed"] or catalog["oracle_truth_allowed"]:
                errors.append("catalog-domain truth/materialization opened before the upstream pin")
            if gates["catalog_materialization_allowed"]:
                errors.append("catalog materialization gate opened before the upstream pin")
            if not pending_forbidden.issubset(plan["execution_partition"]["forbidden_now"]):
                errors.append("pending grammar execution partition omits a fail-closed prohibition")

        if surface_pending:
            if upstream["pin"] is None:
                errors.append("surface-pinned grammar dependency has no specification pin")
            if catalog["status"] != "pinned_refresh_pending":
                errors.append("surface-pinned catalog-domain status hides pending implementation")
            if catalog["materialization_allowed"] or catalog["oracle_truth_allowed"]:
                errors.append("catalog-domain truth opened before the implementation pin")
            if gates["retrieval_contract_refreshed"] or gates["semantic_oracle_refreshed"]:
                errors.append("retrieval/oracle refresh claimed before the implementation pin")
            if gates["catalog_materialization_allowed"]:
                errors.append("catalog materialization gate opened before the implementation pin")
            if not pending_forbidden.issubset(plan["execution_partition"]["forbidden_now"]):
                errors.append("surface-pinned execution partition omits a fail-closed prohibition")

        if pinned and upstream["pin"] is None:
            errors.append("pinned upstream grammar dependency has no evidence pin")
        if pinned:
            from metis_model1.catalog_maintenance_pin import (
                load_catalog_maintenance_pin,
                validate_catalog_maintenance_pin_contract,
            )

            pin = upstream["pin"]
            pin_errors = validate_catalog_maintenance_pin_contract(root)
            errors.extend(f"catalog implementation pin: {error}" for error in pin_errors)
            implementation_ref = pin["implementation_manifest"]
            implementation_path = root / implementation_ref["path"]
            implementation_sha256 = (
                "sha256:" + hashlib.sha256(implementation_path.read_bytes()).hexdigest()
            )
            if implementation_sha256 != implementation_ref["sha256"]:
                errors.append("catalog implementation manifest hash contains drift")
            implementation = load_catalog_maintenance_pin(root)
            if (
                pin["revision"] != implementation["revision"]
                or pin["tree"] != implementation["tree"]
                or pin["language_version"] != implementation["language_version"]
            ):
                errors.append("accuracy plan and catalog implementation pin identities differ")
            role_to_evidence_id = {
                "grammar": "grammar",
                "validator": "validator",
                "compiler": "compiler",
                "ir_contract": "ir_contract",
                "retrieval_contract": "retrieval_contract",
                "semantic_oracle": "retrieval_oracle",
                "tenant_threshold_setting_keys": "tenant_threshold_setting_keys",
            }
            implementation_evidence = {
                item["id"]: {
                    "path": item["path"],
                    "blob_oid": item["blob_oid"],
                    "sha256": item["sha256"],
                }
                for item in implementation["evidence"]
            }
            for role, evidence_id in role_to_evidence_id.items():
                if pin[role] != implementation_evidence.get(evidence_id):
                    errors.append(f"accuracy plan catalog pin evidence differs for {role}")
        refresh_ready = (
            gates["upstream_pin_complete"]
            and gates["retrieval_contract_refreshed"]
            and gates["semantic_oracle_refreshed"]
        )
        from metis_model1.catalog_retrieval_refresh import (
            validate_catalog_retrieval_refresh_contract,
        )

        refresh_contract_errors = validate_catalog_retrieval_refresh_contract(root)
        if gates["retrieval_contract_refreshed"] != gates["semantic_oracle_refreshed"]:
            errors.append("retrieval and semantic-oracle refresh gates must move together")
        if (
            gates["retrieval_contract_refreshed"]
            or gates["semantic_oracle_refreshed"]
            or gates["catalog_materialization_allowed"]
        ) and refresh_contract_errors:
            errors.extend(
                f"catalog retrieval/oracle refresh: {error}" for error in refresh_contract_errors
            )
        if not refresh_ready and not pending_forbidden.issubset(
            plan["execution_partition"]["forbidden_now"]
        ):
            errors.append("pre-refresh execution partition omits a fail-closed prohibition")
        if pending and (
            gates["retrieval_contract_refreshed"] or gates["semantic_oracle_refreshed"]
        ):
            errors.append("retrieval/oracle refresh claimed before the upstream pin")
        if surface_pinned and not refresh_ready:
            if catalog["status"] != "pinned_refresh_pending":
                errors.append("pinned catalog-domain status does not expose pending refresh work")
            if catalog["materialization_allowed"] or catalog["oracle_truth_allowed"]:
                errors.append("catalog-domain truth opened before all refresh gates")
        if refresh_ready and (
            catalog["status"] != "ready_for_materialization"
            or not catalog["materialization_allowed"]
            or not catalog["oracle_truth_allowed"]
        ):
            errors.append("refreshed catalog-domain state is not ready for materialization")
        if catalog["materialization_allowed"] != gates["catalog_materialization_allowed"]:
            errors.append("catalog materialization state disagrees with its gate")
        if catalog["materialization_allowed"] and not refresh_ready:
            errors.append("catalog materialization opened before pin, retrieval and oracle refresh")
        if catalog["oracle_truth_allowed"] and not refresh_ready:
            errors.append("catalog oracle truth opened before pin, retrieval and oracle refresh")
        if catalog["status"] == "ready_for_materialization" and not refresh_ready:
            errors.append("catalog-domain status claims readiness before all refresh gates")
        if refresh_ready:
            if probe_status == "evaluated":
                required_allowed = {"upstream_read_only_pin_monitoring"}
            else:
                required_allowed = {
                    "catalog_domain_prompt_truth",
                    "catalog_domain_oracle_truth",
                    "catalog_probe_spec_and_oracle_truth",
                }
                required_allowed.add(
                    "catalog_probe_pre_output_seal"
                    if probe_status == "spec_ready"
                    else "catalog_probe_evaluation"
                )
            if not required_allowed.issubset(plan["execution_partition"]["allowed_now"]):
                errors.append("refreshed execution partition omits catalog construction work")
            if (
                probe_status == "evaluated"
                and set(plan["execution_partition"]["allowed_now"]) != required_allowed
            ):
                errors.append("evaluated catalog probe leaves completed work active")
            deferred_broad_operations = {
                "non_catalog_d18_task_design",
                "non_catalog_t30_task_and_oracle_design",
                "f6_structural_oracle_implementation",
                "non_catalog_f4_f5_oracle_contract_work",
                "catalog_retrieval_adapter_contract_work",
            }
            if deferred_broad_operations.intersection(plan["execution_partition"]["allowed_now"]):
                errors.append("postponed broad accuracy work remains in the active partition")
            required_forbidden = {
                "t30_model_outputs_before_complete_seal",
                "tenant_value_payloads",
                "training",
            }
            if probe_status == "spec_ready":
                required_forbidden.add("catalog_probe_model_outputs_before_probe_seal")
            if probe_status == "evaluated":
                required_forbidden.add("catalog_probe_additional_model_outputs")
            if not required_forbidden.issubset(plan["execution_partition"]["forbidden_now"]):
                errors.append("refreshed execution partition omits persistent prohibitions")
            if required_allowed.intersection(plan["execution_partition"]["forbidden_now"]):
                errors.append("refreshed catalog construction remains contradictory")

        final_test = wave["final_test"]
        benchmark_evidence = plan["maintenance_benchmark_evidence"]
        if any(
            wave[name]["materialized"] != 0 for name in ("diagnostic", "train", "dev", "final_test")
        ):
            errors.append(
                "broad D18/train/dev/T30 materialization remains forbidden "
                "while the probe is active"
            )
        if (
            final_test["seal_status"] == "sealed_pre_output"
            or gates["t30_sealed_before_model_outputs"]
            or gates["model_evaluation_allowed"]
        ):
            errors.append(
                "maintenance benchmark Git pre-output verifier is not integrated; "
                "seal and evaluation remain fail-closed"
            )
        t30_sealed = (
            final_test["seal_status"] == "sealed_pre_output"
            and final_test["materialized"] == final_test["total"]
            and benchmark_evidence["roster"] is not None
            and benchmark_evidence["pre_output_seal"] is not None
        )
        if gates["t30_sealed_before_model_outputs"] != t30_sealed:
            errors.append("T30 seal gate disagrees with its materialized pre-output state")
        if final_test["seal_status"] == "sealed_pre_output" and (
            benchmark_evidence["roster"] is None or benchmark_evidence["pre_output_seal"] is None
        ):
            errors.append("T30 claims a seal without verified roster and pre-output evidence")
        if final_test["seal_status"] == "sealed_pre_output" and (
            final_test["materialized"] != final_test["total"]
        ):
            errors.append("T30 claims a seal without all 30 materialized tasks")
        if final_test["seal_status"] == "not_sealed" and any(
            benchmark_evidence[name] is not None for name in ("pre_output_seal", "decision_report")
        ):
            errors.append("unsealed T30 carries seal or decision evidence")
        if final_test["materialized"] == 0 and benchmark_evidence["roster"] is not None:
            errors.append("unmaterialized maintenance benchmark carries roster evidence")
        if (
            benchmark_evidence["decision_report"] is not None
            and not gates["model_evaluation_allowed"]
        ):
            errors.append("maintenance decision evidence exists before model evaluation is allowed")
        if gates["model_evaluation_allowed"] and not t30_sealed:
            errors.append("model evaluation opened before the complete T30 pre-output seal")
        if gates["model_evaluation_allowed"] and not refresh_ready:
            errors.append("model evaluation opened before pin, retrieval and oracle refresh")
        if (
            wave["diagnostic"]["model_outputs_allowed"] != gates["model_evaluation_allowed"]
            or final_test["model_outputs_allowed"] != gates["model_evaluation_allowed"]
        ):
            errors.append("model-output flags disagree with the evaluation gate")
        if gates["training_allowed"]:
            errors.append("accuracy-uplift planning contract cannot authorize training")

        if surface_pending:
            if plan["status"] != "pin_refresh_active" or gates["active_work"] != "pin_refresh":
                errors.append("surface-pending plan status or active-work state contains drift")
            required_nonclaims = {
                "no_upstream_implementation_pin",
                "no_catalog_domain_dataset",
                "no_model_output",
                "no_previous_adapter",
                "no_training_authority",
                "no_accuracy_claim",
                "nonpromotable",
            }
            if not required_nonclaims.issubset(plan["nonclaims"]):
                errors.append("surface-pending plan omits required nonclaims")
        if pinned and not refresh_ready:
            if (
                plan["status"] != "retrieval_refresh_active"
                or gates["active_work"] != "retrieval_refresh"
            ):
                errors.append(
                    "implementation-pinned plan status or active-work state contains drift"
                )
            if (
                "catalog_retrieval_adapter_contract_work"
                not in plan["execution_partition"]["allowed_now"]
            ):
                errors.append("implementation-pinned plan omits retrieval adapter contract work")
            required_nonclaims = {
                "no_retrieval_refresh",
                "no_semantic_oracle_refresh",
                "no_catalog_domain_dataset",
                "no_model_output",
                "no_previous_adapter",
                "no_training_authority",
                "no_accuracy_claim",
                "nonpromotable",
            }
            if not required_nonclaims.issubset(plan["nonclaims"]):
                errors.append("implementation-pinned plan omits required refresh nonclaims")
        if pinned and refresh_ready:
            if probe_status == "evaluated":
                expected_status = "maintenance_diagnosed"
                expected_active_work = "catalog_probe_diagnosis_complete"
            else:
                expected_status = "benchmark_construction_active"
                expected_active_work = (
                    "catalog_probe_pre_output_seal"
                    if probe_status == "spec_ready"
                    else "maintenance_evaluation"
                )
            if plan["status"] != expected_status or gates["active_work"] != expected_active_work:
                errors.append("refreshed plan status or active-work state contains drift")
            stale_nonclaims = {"no_retrieval_refresh", "no_semantic_oracle_refresh"}
            if stale_nonclaims.intersection(plan["nonclaims"]):
                errors.append("refreshed plan retains stale refresh nonclaims")
            required_nonclaims = {
                "no_catalog_domain_dataset",
                "no_tenant_dataset_authority",
                "no_previous_adapter",
                "no_training_authority",
                "no_accuracy_claim",
                "nonpromotable",
            }
            required_nonclaims.add(
                "no_broad_model_output" if probe_status == "evaluated" else "no_model_output"
            )
            if not required_nonclaims.issubset(plan["nonclaims"]):
                errors.append("refreshed plan omits required construction nonclaims")
            if probe_status == "evaluated" and "no_model_output" in plan["nonclaims"]:
                errors.append("evaluated catalog probe falsely claims no model output")

        maintenance = plan["maintenance"]
        if maintenance["default_verdict"] != "NO_INITIAL_TRAIN":
            errors.append("accuracy-uplift default verdict is not NO_INITIAL_TRAIN")
        d18_decision = maintenance["d18_decision"]
        if (
            d18_decision["total"] != wave["diagnostic"]["total"]
            or d18_decision["no_initial_train_semantic_correct_minimum"] != 17
            or d18_decision["per_family_semantic_correct_minimum"] != 2
        ):
            errors.append("D18 decision thresholds contain drift")
        t30_confirmation = maintenance["t30_confirmation"]
        if (
            t30_confirmation["total"] != final_test["total"]
            or t30_confirmation["local_confirm_semantic_correct_minimum"] != 29
            or t30_confirmation["per_family_semantic_correct_minimum"] != 4
            or t30_confirmation["training_feedback_allowed"]
            or t30_confirmation["claim_scope"] != "observed_local_only"
        ):
            errors.append("T30 confirmation thresholds or no-feedback scope contain drift")
        condition = maintenance["training_open_condition"]
        if (
            condition["minimum_correctable_semantic_failures"] < 3
            or condition["minimum_distinct_roots"] < 2
        ):
            errors.append("delta training condition is weaker than three failures/two roots")
        if (
            maintenance["delta_qlora"]["mode"] != "bounded_initial_micro_qlora"
            or maintenance["delta_qlora"]["checkpoint_selection"] != "dev_only"
            or maintenance["delta_qlora"]["final_test_feedback_allowed"]
        ):
            errors.append("initial micro-QLoRA contract or final-test isolation contains drift")

        repository_files = git_repository_files(root)
        boundary_errors = validate_artifact_policy_paths(repository_files)
        boundary_errors.extend(validate_repository_file_contents(root, repository_files))
        errors.extend(f"repository boundary: {error}" for error in boundary_errors)
        return errors
    except Exception as error:  # noqa: BLE001 - the plan gate must fail closed
        return [f"accuracy-uplift plan unreadable: {type(error).__name__}: {error}"]


def validate_hyperparameter_grid_contract(root: Path) -> list[str]:
    grid, schema_errors = _validate_standalone_contract_schema(
        root,
        "schemas/hyperparameter-grid.schema.json",
        "manifests/hyperparameter-grid.json",
    )
    # Const mutations preserve the object shape, so retain the historical
    # semantic diagnostics as well as the schema error.  Structural/type
    # failures cannot be safely inspected by the semantic pass.
    if schema_errors and any(not error.endswith(" was expected") for error in schema_errors):
        return schema_errors
    errors: list[str] = list(schema_errors)
    configurations = grid["screening"]["configurations"]
    expected = {
        ("r8-a16-lr1e-5", 8, 16, 0.00001),
        ("r8-a16-lr2e-5", 8, 16, 0.00002),
        ("r16-a32-lr1e-5", 16, 32, 0.00001),
        ("r16-a32-lr2e-5", 16, 32, 0.00002),
    }
    observed = {
        (item["id"], item["lora_rank"], item["lora_alpha"], item["learning_rate"])
        for item in configurations
    }
    if observed != expected or len(configurations) != len(expected):
        errors.append("W5 grid must be the exact four-configuration rank/LR Cartesian set")
    if any(item["lora_alpha"] != 2 * item["lora_rank"] for item in configurations):
        errors.append("W5 grid alpha must remain exactly twice the rank")

    finalists = grid["finalist_repeats"]
    if finalists["seeds"] != [17, 29, 43]:
        errors.append("W5 finalist seed roster contains drift")
    budget = grid["budget"]
    expected_screening_steps = (
        len(configurations) * grid["screening"]["max_optimizer_steps_per_configuration"]
    )
    expected_finalist_steps = len(finalists["seeds"]) * finalists["max_optimizer_steps_per_seed"]
    if budget["max_screening_optimizer_steps"] != expected_screening_steps:
        errors.append("W5 screening step budget is inconsistent")
    if budget["max_finalist_optimizer_steps"] != expected_finalist_steps:
        errors.append("W5 finalist step budget is inconsistent")
    if budget["max_total_optimizer_steps"] != expected_screening_steps + expected_finalist_steps:
        errors.append("W5 total step budget is inconsistent")

    probes = grid["technical_evidence"]["probes"]
    probe_by_id = {item["id"]: item for item in probes}
    if set(probe_by_id) != {"rank8-step1", "rank8-resume-step2", "rank16-step1"}:
        errors.append("W5 grid technical probe roster contains drift")
    if len(probe_by_id) != len(probes):
        errors.append("W5 grid technical probes contain duplicate IDs")
    if any(not item["finite"] for item in probes):
        errors.append("W5 grid contains a non-finite technical probe")
    if any(item["peak_metal_gb"] > grid["fixed"]["max_peak_metal_gb"] for item in probes):
        errors.append("W5 grid contains a probe above the Metal memory stop")
    if probe_by_id.get("rank8-resume-step2", {}).get("resume") is not True:
        errors.append("W5 grid lacks the required sequence-1024 rank-8 resume probe")

    if not errors:
        rank8_bytes = max(item["checkpoint_bytes"] for item in probes if item["rank"] == 8)
        rank16_bytes = max(item["checkpoint_bytes"] for item in probes if item["rank"] == 16)
        screening_bytes = 2 * rank8_bytes + 2 * rank16_bytes
        finalist_bytes = len(finalists["seeds"]) * 4 * rank16_bytes
        if (
            budget["max_total_published_checkpoint_bytes_estimate"]
            != screening_bytes + finalist_bytes
        ):
            errors.append("W5 checkpoint storage estimate is inconsistent with worst-case rank")
    if (
        budget["max_total_published_checkpoint_bytes_estimate"]
        > budget["max_total_published_checkpoint_bytes"]
    ):
        errors.append("W5 checkpoint estimate exceeds the sweep storage cap")
    artifact_policy = load_json(root / "manifests/artifact-store-policy.json")
    if (
        budget["max_total_published_checkpoint_bytes"]
        > artifact_policy["budget"]["per_run_cap_bytes"]
    ):
        errors.append("W5 sweep cap exceeds the ratified local artifact-store cap")

    register = load_json(root / "manifests/decision-register.json")
    decision = next(
        (item for item in register["open_decisions"] if item["id"] == "O-005"),
        None,
    )
    if (
        decision is None
        or decision["status"] != "ratified"
        or decision["blocks"]
        or not decision["resolution"]
    ):
        errors.append("O-005 is not fully ratified in the decision register")
    return errors


def validate_qualification_contract(root: Path) -> list[str]:
    runtime = load_json(root / "qualification/runtime-pin.json")
    checkpoint = load_json(root / "qualification/checkpoint-pin.json")
    source_manifest = load_json(root / "manifests/source-model-revisions.json")
    project = tomllib.loads((root / "qualification/pyproject.toml").read_text(encoding="utf-8"))
    errors: list[str] = []

    lock_hash = hashlib.sha256((root / "qualification/uv.lock").read_bytes()).hexdigest()
    if runtime["lock_sha256"] != lock_hash:
        errors.append("qualification runtime lock hash does not match qualification/uv.lock")

    dependency_pins = set(project["project"]["dependencies"])
    for package in (
        "datasets",
        "jinja2",
        "mlx",
        "mlx-vlm",
        "numpy",
        "psutil",
        "safetensors",
        "transformers",
    ):
        expected = f"{package}=={runtime['packages'][package]}"
        if expected not in dependency_pins:
            errors.append(f"qualification dependency pin is missing: {expected}")

    expected_revision = next(
        model["revision"]
        for model in source_manifest["models"]
        if model["role"] == "mlx_checkpoint"
    )
    if checkpoint["revision"] != expected_revision:
        errors.append("qualification checkpoint revision differs from the source manifest")
    if checkpoint["resolved_revision"] != expected_revision:
        errors.append("qualification resolved checkpoint revision differs from the source manifest")
    weight_files = checkpoint["weight_files"]
    if checkpoint["payload_bytes"] != sum(item["bytes"] for item in weight_files):
        errors.append("qualification checkpoint payload byte total is inconsistent")
    if len({item["path"] for item in weight_files}) != len(weight_files):
        errors.append("qualification checkpoint contains duplicate weight paths")
    if len({item["sha256"] for item in weight_files}) != len(weight_files):
        errors.append("qualification checkpoint contains duplicate weight hashes")
    if runtime["resume_semantics"] != "adapter_weights_only_no_optimizer_rng_or_global_step":
        errors.append("qualification runtime overstates upstream resume semantics")
    if runtime.get("status") != "qualified":
        errors.append("qualification runtime is not marked qualified")
    if runtime.get("qualification_remaining") != []:
        errors.append("qualification runtime retains incomplete gates")
    if (
        runtime.get("full_state_resume_semantics")
        != "local_wrapper_optimizer_rng_sampler_global_step_bit_exact_stop_resume"
    ):
        errors.append("qualification full-state resume semantics are missing or overstated")
    report_path = runtime.get("qualification_report")
    if not isinstance(report_path, str) or not (root / report_path).is_file():
        errors.append("qualification report is missing")
    wrapper_hash = hashlib.sha256(
        (root / "qualification/train_full_state.py").read_bytes()
    ).hexdigest()
    if runtime.get("qualification_wrapper_sha256") != wrapper_hash:
        errors.append("qualification wrapper hash differs from the qualified runtime pin")

    source_runtime = source_manifest["runtime"]
    if source_manifest["state"] != "ratified":
        errors.append("qualified runtime requires a ratified source/model manifest")
    if source_runtime["status"] != "qualified":
        errors.append("source/model manifest runtime is not qualified")
    if source_runtime["pinned_version"] != runtime["packages"]["mlx-vlm"]:
        errors.append("source/model manifest runtime pin differs from qualification runtime")
    if source_manifest["open_decision_refs"]:
        errors.append("qualified source/model manifest retains open decision references")

    register = load_json(root / "manifests/decision-register.json")
    decision = next(
        (item for item in register["open_decisions"] if item["id"] == "O-004"),
        None,
    )
    if (
        decision is None
        or decision["status"] != "ratified"
        or decision["blocks"]
        or not decision["resolution"]
    ):
        errors.append("O-004 is not fully ratified in the decision register")
    return errors


def validate_artifact_policy_paths(paths: list[str]) -> list[str]:
    errors: list[str] = []
    for raw_path in paths:
        path = PurePosixPath(raw_path)
        normalized = path.as_posix()
        suffix = path.suffix.lower()
        name = path.name.lower()
        if name == ".env" or name.startswith(".env.") or name in FORBIDDEN_SECRET_NAMES:
            errors.append(f"repository secret-bearing path is forbidden: {normalized}")
        if suffix in FORBIDDEN_SECRET_SUFFIXES:
            errors.append(f"repository key material is forbidden: {normalized}")
        if suffix in FORBIDDEN_MODEL_SUFFIXES:
            errors.append(f"repository model payload is forbidden: {normalized}")
        if suffix in FORBIDDEN_DATA_SUFFIXES or name.endswith(".db"):
            errors.append(f"repository materialized data is forbidden: {normalized}")
        if any(normalized.startswith(prefix) for prefix in FORBIDDEN_REPOSITORY_PREFIXES):
            errors.append(f"repository local-only artifact is forbidden: {normalized}")
    return errors


def validate_repository_file_contents(root: Path, paths: list[str]) -> list[str]:
    errors: list[str] = []
    for raw_path in paths:
        path = root / raw_path
        if path.is_symlink():
            errors.append(f"repository symlink is forbidden: {raw_path}")
            continue
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_REPOSITORY_FILE_BYTES:
            errors.append(f"repository file exceeds {MAX_REPOSITORY_FILE_BYTES} bytes: {raw_path}")
            continue
        payload = path.read_bytes()
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"binary repository file is forbidden: {raw_path}")
            continue
        if any(marker in text for marker in PRIVATE_KEY_MARKERS):
            errors.append(f"private key material is forbidden: {raw_path}")
    return errors


def git_repository_files(root: Path) -> list[str]:
    process = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in process.stdout.split(b"\0") if item]


def _collect_wave_blocks(register: dict[str, Any]) -> dict[str, list[str]]:
    blocked: dict[str, list[str]] = {}
    for decision in register["open_decisions"]:
        if decision["status"] != "open":
            continue
        for wave in decision["blocks"]:
            blocked.setdefault(wave, []).append(decision["id"])
    return {wave: sorted(decision_ids) for wave, decision_ids in sorted(blocked.items())}


def _collect_nonblocking_open(register: dict[str, Any]) -> list[str]:
    return sorted(
        decision["id"]
        for decision in register["open_decisions"]
        if decision["status"] == "open" and not decision["blocks"]
    )


def validate_w3_retained_report_schema_contract(root: Path | None = None) -> list[str]:
    """Bind the six W3 report variants to the deferred-cleanup wire contract."""

    root = (root or repository_root()).resolve()
    qualification = load_json(root / "schemas/w3-qualification.schema.json")
    bridge = load_json(root / "schemas/w3-bridge-replay.schema.json")
    errors: list[str] = []
    expected_variant_keys = {
        "qualified": {
            "schema_version",
            "qualification_id",
            "status",
            "claim",
            "authority_manifest_sha256",
            "bundle_sha256",
            "semantic_registry_sha256",
            "candidate_manifest_sha256",
            "worker_input_sha256",
            "worker_output_sha256",
            "launcher",
            "counts",
            "roles",
            "executions",
            "stops",
            "cleanup",
            "manifest_sha256",
        },
        "blocked": {
            "schema_version",
            "qualification_id",
            "status",
            "claim",
            "reason",
            "cleanup",
        },
        "productionQualified": {
            "schema_version",
            "qualification_id",
            "qualification_kind",
            "status",
            "claim",
            "authority_manifest_sha256",
            "ratification_evidence_sha256",
            "project_revision",
            "source_bundle_manifest_sha256",
            "dependency_bundle_manifest_sha256",
            "dependency_roster_sha256",
            "capsule_manifest_sha256",
            "candidate_manifest_sha256",
            "semantic_registry_sha256",
            "worker_input_sha256",
            "worker_output_sha256",
            "launcher",
            "counts",
            "roles",
            "executions",
            "native_evidence",
            "non_claims",
            "cleanup",
            "manifest_sha256",
        },
        "productionBlocked": {
            "schema_version",
            "qualification_id",
            "qualification_kind",
            "status",
            "claim",
            "reason",
            "native_evidence",
            "cleanup",
        },
    }
    qualifier_cleanup_refs = {
        "qualified": "#/$defs/qualifiedV1Cleanup",
        "blocked": "#/$defs/blockedV1Cleanup",
        "productionQualified": "#/$defs/qualifiedV3Cleanup",
        "productionBlocked": "#/$defs/blockedV3Cleanup",
    }
    for name, expected_keys in expected_variant_keys.items():
        variant = qualification.get("$defs", {}).get(name, {})
        if "cleanup" not in variant.get("required", ()):
            errors.append(f"W3 qualification {name} does not require cleanup")
        if variant.get("properties", {}).get("cleanup") != {"$ref": qualifier_cleanup_refs[name]}:
            errors.append(f"W3 qualification {name} cleanup schema binding drifted")
        if (
            variant.get("additionalProperties") is not False
            or set(variant.get("required", ())) != expected_keys
            or set(variant.get("properties", {})) != expected_keys
        ):
            errors.append(f"W3 qualification {name} required-key contract drifted")
    for document, label in ((qualification, "qualification"), (bridge, "bridge")):
        cleanup = document.get("$defs", {}).get("cleanup", {})
        properties = cleanup.get("properties", {})
        if properties.get("status") != {"const": "cleanup_deferred"}:
            errors.append(f"W3 {label} cleanup status drifted")
        if properties.get("gc_policy") != {"const": "separately_ratified_quiescent_exclusive_v1"}:
            errors.append(f"W3 {label} GC policy drifted")
        if properties.get("delete_attempts") != {"const": 0}:
            errors.append(f"W3 {label} delete-attempt contract drifted")
    exact_cleanup_rosters = (
        (
            qualification,
            "qualifiedV1Cleanup",
            1,
            ["#/$defs/workerProcessRoot"],
            "qualification v1",
        ),
        (
            qualification,
            "qualifiedV3Cleanup",
            3,
            [
                "#/$defs/productionProcessRoot",
                "#/$defs/productionRuntimeRoot",
                "#/$defs/productionTrustedRoot",
            ],
            "qualification v3",
        ),
        (
            qualification,
            "blockedV1Cleanup",
            0,
            [
                "#/$defs/workerProcessBlockedRoot",
                "#/$defs/publicationPartialBlockedRoot",
            ],
            "blocked qualification v1",
        ),
        (
            qualification,
            "blockedV3Cleanup",
            0,
            [
                "#/$defs/productionProcessBlockedRoot",
                "#/$defs/productionRuntimeBlockedRoot",
                "#/$defs/productionTrustedBlockedRoot",
                "#/$defs/publicationPartialBlockedRoot",
            ],
            "blocked qualification v3",
        ),
        (
            bridge,
            "qualifiedChildCleanup",
            3,
            [
                "#/$defs/productionProcessRoot",
                "#/$defs/productionRuntimeRoot",
                "#/$defs/productionTrustedRoot",
            ],
            "bridge child",
        ),
        (
            bridge,
            "qualifiedReplayCleanup",
            1,
            ["#/$defs/replayHolderRoot"],
            "bridge holder",
        ),
        (
            bridge,
            "blockedChildCleanup",
            0,
            [
                "#/$defs/productionProcessBlockedRoot",
                "#/$defs/productionRuntimeBlockedRoot",
                "#/$defs/productionTrustedBlockedRoot",
                "#/$defs/publicationPartialBlockedRoot",
            ],
            "blocked bridge child",
        ),
        (
            bridge,
            "blockedReplayCleanup",
            0,
            ["#/$defs/replayHolderBlockedRoot"],
            "blocked bridge holder",
        ),
    )
    for document, definition, minimum, expected_refs, label in exact_cleanup_rosters:
        cleanup_definition = document.get("$defs", {}).get(definition, {})
        properties = cleanup_definition.get("properties", {})
        roster = properties.get("retained_roots", {})
        observed_refs = [item.get("$ref") for item in roster.get("prefixItems", ())]
        if (
            cleanup_definition.get("additionalProperties") is not False
            or set(cleanup_definition.get("required", ()))
            != {"status", "gc_policy", "delete_attempts", "retained_roots"}
            or properties.get("status") != {"const": "cleanup_deferred"}
            or properties.get("gc_policy")
            != {"const": "separately_ratified_quiescent_exclusive_v1"}
            or properties.get("delete_attempts") != {"const": 0}
            or roster.get("minItems") != minimum
            or roster.get("maxItems") != len(expected_refs)
            or roster.get("items") is not False
            or observed_refs != expected_refs
        ):
            errors.append(f"W3 {label} retained-root roster binding drifted")
    blocked_root_unions = (
        (
            qualification,
            "workerProcessBlockedRoot",
            ("workerProcessRoot", "workerProcessUnmeasurable"),
            "qualification worker",
        ),
        (
            qualification,
            "productionProcessBlockedRoot",
            ("productionProcessRoot", "productionProcessUnmeasurable"),
            "qualification process",
        ),
        (
            qualification,
            "productionRuntimeBlockedRoot",
            ("productionRuntimeRoot", "productionRuntimeUnmeasurable"),
            "qualification runtime",
        ),
        (
            qualification,
            "productionTrustedBlockedRoot",
            ("productionTrustedRoot", "productionTrustedUnmeasurable"),
            "qualification trusted",
        ),
        (
            qualification,
            "publicationPartialBlockedRoot",
            ("publicationPartialRoot", "publicationPartialUnmeasurable"),
            "qualification publication",
        ),
        (
            bridge,
            "productionProcessBlockedRoot",
            ("productionProcessRoot", "productionProcessUnmeasurable"),
            "bridge process",
        ),
        (
            bridge,
            "productionRuntimeBlockedRoot",
            ("productionRuntimeRoot", "productionRuntimeUnmeasurable"),
            "bridge runtime",
        ),
        (
            bridge,
            "productionTrustedBlockedRoot",
            ("productionTrustedRoot", "productionTrustedUnmeasurable"),
            "bridge trusted",
        ),
        (
            bridge,
            "publicationPartialBlockedRoot",
            ("publicationPartialRoot", "publicationPartialUnmeasurable"),
            "bridge publication",
        ),
        (
            bridge,
            "replayHolderBlockedRoot",
            ("replayHolderRoot", "replayHolderUnmeasurable"),
            "bridge holder",
        ),
    )
    for document, definition, expected_definitions, label in blocked_root_unions:
        observed_refs = [
            item.get("$ref")
            for item in document.get("$defs", {}).get(definition, {}).get("oneOf", ())
        ]
        expected_refs = [f"#/$defs/{name}" for name in expected_definitions]
        if observed_refs != expected_refs:
            errors.append(f"W3 blocked {label} sealed/unmeasurable union drifted")
    expected_count_caps = (
        (qualification, "processRetainedCounts", (512, 512, 134217728), "qualification process"),
        (qualification, "runtimeRetainedCounts", (8, 8, 134217728), "qualification runtime"),
        (qualification, "trustedRetainedCounts", (4096, 4096, 1073741824), "qualification trusted"),
        (
            qualification,
            "publicationRetainedCounts",
            (128, 128, 33554432),
            "qualification publication",
        ),
        (bridge, "processRootCounts", (512, 512, 134217728), "bridge process"),
        (bridge, "runtimeRootCounts", (8, 8, 134217728), "bridge runtime"),
        (bridge, "trustedRootCounts", (4096, 4096, 1073741824), "bridge trusted"),
        (bridge, "publicationRootCounts", (128, 128, 33554432), "bridge publication"),
        (bridge, "holderRootCounts", (16384, 16384, 3221225472), "bridge holder"),
    )
    for document, definition, expected_caps, label in expected_count_caps:
        properties = document.get("$defs", {}).get(definition, {}).get("properties", {})
        observed_caps = tuple(
            properties.get(name, {}).get("maximum") for name in ("files", "directories", "bytes")
        )
        if observed_caps != expected_caps:
            errors.append(f"W3 {label} retained-root caps drifted")
    bridge_variant_keys = {
        "qualified": {
            "schema_version",
            "replay_id",
            "status",
            "claim",
            "authority_manifest_sha256",
            "runs",
            "normalized_projection_sha256",
            "capsule_manifest_sha256",
            "counts",
            "roles",
            "nonce_model",
            "artifacts",
            "native_evidence",
            "non_claims",
            "cleanup",
            "manifest_sha256",
        },
        "blocked": {
            "schema_version",
            "replay_id",
            "status",
            "claim",
            "reason",
            "observed_runs",
            "native_evidence",
            "cleanup",
        },
    }
    bridge_cleanup_refs = {
        "qualified": "#/$defs/qualifiedReplayCleanup",
        "blocked": "#/$defs/blockedReplayCleanup",
    }
    for name, expected_keys in bridge_variant_keys.items():
        variant = bridge.get("$defs", {}).get(name, {})
        if "cleanup" not in variant.get("required", ()):
            errors.append(f"W3 bridge {name} does not require cleanup")
        if variant.get("properties", {}).get("cleanup") != {"$ref": bridge_cleanup_refs[name]}:
            errors.append(f"W3 bridge {name} cleanup schema binding drifted")
        if (
            variant.get("additionalProperties") is not False
            or set(variant.get("required", ())) != expected_keys
            or set(variant.get("properties", {})) != expected_keys
        ):
            errors.append(f"W3 bridge {name} required-key contract drifted")
    qualified = bridge.get("$defs", {}).get("qualified", {})
    required = set(qualified.get("required", ()))
    if bridge.get("$defs", {}).get("qualified", {}).get("properties", {}).get("schema_version") != {
        "const": 3
    }:
        errors.append("W3 bridge qualified schema version is not v3")
    if not {"runs", "normalized_projection_sha256"}.issubset(required):
        errors.append("W3 bridge qualified physical/normalized replay binding is incomplete")
    if {"qualification_manifest_sha256", "reports_sha256"} & required:
        errors.append("W3 bridge qualified retains a legacy singular replay digest")
    if bridge.get("$defs", {}).get("physicalRun", {}).get("properties", {}).get("cleanup") != {
        "$ref": "#/$defs/qualifiedChildCleanup"
    }:
        errors.append("W3 bridge physical-run cleanup roster binding drifted")
    observed_run_refs = [
        item.get("$ref") for item in bridge.get("$defs", {}).get("observedRun", {}).get("oneOf", ())
    ]
    if observed_run_refs != [
        "#/$defs/qualifiedObservedRun",
        "#/$defs/blockedObservedRun",
        "#/$defs/noReportObservedRun",
    ]:
        errors.append("W3 bridge observed-run status contract drifted")
    if bridge.get("$defs", {}).get("qualifiedObservedRun", {}).get("properties", {}).get(
        "cleanup"
    ) != {"$ref": "#/$defs/qualifiedChildCleanup"}:
        errors.append("W3 bridge qualified observed-run cleanup roster binding drifted")
    if bridge.get("$defs", {}).get("blockedObservedRun", {}).get("properties", {}).get(
        "cleanup"
    ) != {"$ref": "#/$defs/blockedChildCleanup"}:
        errors.append("W3 bridge blocked observed-run cleanup roster binding drifted")
    observed_roster = (
        bridge.get("$defs", {}).get("blocked", {}).get("properties", {}).get("observed_runs", {})
    )
    if (
        observed_roster.get("minItems") != 0
        or observed_roster.get("maxItems") != 2
        or observed_roster.get("items") is not False
        or [item.get("$ref") for item in observed_roster.get("prefixItems", ())]
        != ["#/$defs/observedRun1", "#/$defs/observedRun2"]
    ):
        errors.append("W3 bridge blocked observed-run prefix order drifted")
    for index in (1, 2):
        expected = [
            {"$ref": "#/$defs/observedRun"},
            {"properties": {"run_index": {"const": index}}},
        ]
        if bridge.get("$defs", {}).get(f"observedRun{index}", {}).get("allOf") != expected:
            errors.append(f"W3 bridge observed-run {index} index binding drifted")
    return errors


def validate_w1_w2_evidence_package(root: Path) -> list[str]:
    """Fail closed on semantic drift across the six W1/W2 evidence sidecars.

    JSON Schema proves only their fixed wire shape.  Each sidecar's own
    deterministic validator binds that shape to the current frozen inputs and
    retains the intentionally unresolved W1/W2 state.
    """

    from metis_model1.w1_blockers import validate_blocker_map
    from metis_model1.w1_seal import (
        validate_benchmark_seal,
        validate_held_out_map,
        validate_leakage_assignment,
        validate_oracle_receipts,
    )
    from metis_model1.w2_rights import validate_rights_dossier

    validators = (
        (
            "w1-blocker-map",
            "manifests/w1-slice-30-blocker-map-v1.json",
            lambda instance: validate_blocker_map(instance, root),
        ),
        (
            "w2-rights-dossier",
            "manifests/w2-rights-dossier-v1.json",
            validate_rights_dossier,
        ),
        (
            "w1-oracle-receipts",
            "manifests/w1-slice-30-oracle-receipts-v1.json",
            lambda instance: validate_oracle_receipts(instance, root),
        ),
        (
            "w1-leakage-assignment",
            "manifests/w1-leakage-group-assignment-v1.json",
            lambda instance: validate_leakage_assignment(instance, root),
        ),
        (
            "w1-held-out-map",
            "manifests/w1-held-out-family-map-v1.json",
            lambda instance: validate_held_out_map(instance, root),
        ),
        (
            "w1-benchmark-seal",
            "manifests/w1-benchmark-seal-v1.json",
            lambda instance: validate_benchmark_seal(instance, root),
        ),
    )
    errors: list[str] = []
    for label, relative_path, validator in validators:
        try:
            semantic_errors = validator(load_json(root / relative_path))
        except Exception as error:  # Fail closed at the contract/validator boundary.
            errors.append(f"{label}: semantic validator raised {type(error).__name__}: {error}")
            continue
        errors.extend(f"{label}: {error}" for error in semantic_errors)
    return errors


def validate_foundation(root: Path | None = None) -> ValidationReport:
    root = (root or repository_root()).resolve()
    report = ValidationReport()

    for relative_path in REQUIRED_FOUNDATION_PATHS:
        if not (root / relative_path).is_file():
            report.errors.append(f"required foundation file is missing: {relative_path}")
    if not report.errors:
        report.passes.append(f"foundation-files={len(REQUIRED_FOUNDATION_PATHS)}")

    for schema_path, instance_path in CONTRACT_PAIRS:
        schema = load_json(root / schema_path)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            report.errors.append(f"invalid schema {schema_path}: {error.message}")
            continue

        instance_errors = validate_instance(load_json(root / instance_path), schema)
        if instance_errors:
            report.errors.extend(f"{instance_path}: {error}" for error in instance_errors)
        else:
            report.passes.append(f"contract={instance_path}")

    for schema_path in STANDALONE_SCHEMAS:
        schema = load_json(root / schema_path)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            report.errors.append(f"invalid schema {schema_path}: {error.message}")
        else:
            report.passes.append(f"schema={schema_path}")

    retained_schema_errors = validate_w3_retained_report_schema_contract(root)
    if retained_schema_errors:
        report.errors.extend(retained_schema_errors)
    else:
        report.passes.append("w3-retained-report-schemas=6/6")

    decision_errors = validate_cross_contracts(root)
    if decision_errors:
        report.errors.extend(decision_errors)
    else:
        report.passes.append("cross-contracts=pass")

    benchmark_plan_errors = validate_benchmark_plan_contract(root)
    if benchmark_plan_errors:
        report.errors.extend(benchmark_plan_errors)
    else:
        report.passes.append("benchmark-plan=6-families/30-allocations")

    accuracy_target_errors = validate_accuracy_target_contract(root)
    if accuracy_target_errors:
        report.errors.extend(accuracy_target_errors)
    else:
        report.passes.append("accuracy-target=600/Wilson-95/lower-99/max-failures-1")

    artifact_store_errors = validate_artifact_store_policy_contract(root)
    if artifact_store_errors:
        report.errors.extend(artifact_store_errors)
    else:
        report.passes.append("artifact-store=local-only/40GiB-cap/atomic/no-auto-delete")

    from metis_model1.catalog_maintenance_pin import (
        validate_catalog_maintenance_pin_contract,
    )

    catalog_pin_errors = validate_catalog_maintenance_pin_contract(root)
    if catalog_pin_errors:
        report.errors.extend(f"catalog-maintenance-pin: {error}" for error in catalog_pin_errors)
    else:
        report.passes.append("catalog-maintenance-pin-contract=18-evidence+5-probes-registered")

    from metis_model1.catalog_retrieval_refresh import (
        validate_catalog_retrieval_refresh_contract,
    )

    catalog_refresh_errors = validate_catalog_retrieval_refresh_contract(root)
    if catalog_refresh_errors:
        report.errors.extend(
            f"catalog-retrieval-refresh: {error}" for error in catalog_refresh_errors
        )
    else:
        report.passes.append("catalog-retrieval-refresh=public-synthetic/8-goldens/redacted")

    catalog_probe_errors = validate_catalog_maintenance_probe_contract(root)
    if catalog_probe_errors:
        report.errors.extend(
            f"catalog-maintenance-probe: {error}" for error in catalog_probe_errors
        )
    else:
        probe_plan = load_json(root / "manifests/accuracy-uplift-plan.json")[
            "catalog_maintenance_probe"
        ]
        result = (
            "diagnose-2-of-8/output-observed"
            if probe_plan["status"] == "evaluated"
            else "no-output"
        )
        report.passes.append(
            f"catalog-maintenance-probe=8-cases/{probe_plan['status'].replace('_', '-')}/{result}"
        )

    catalog_successor_errors = validate_catalog_maintenance_successor_contract(root)
    if catalog_successor_errors:
        report.errors.extend(
            f"catalog-maintenance-successor: {error}" for error in catalog_successor_errors
        )
    else:
        successor_decision_path = root / "manifests/catalog-maintenance-successor-decision-v1.json"
        if successor_decision_path.is_file():
            successor_decision = load_json(successor_decision_path)
            report.passes.append(
                "catalog-maintenance-successor=8-cases/terminal-"
                f"{str(successor_decision['status']).lower()}-"
                f"{successor_decision['result']['semantic_correct']}-of-8/no-training"
            )
        else:
            report.passes.append("catalog-maintenance-successor=8-cases/static/no-training")

    catalog_successor_evidence_errors = validate_catalog_maintenance_successor_evidence_contract(
        root
    )
    if catalog_successor_evidence_errors:
        report.errors.extend(
            f"catalog-maintenance-successor-evidence: {error}"
            for error in catalog_successor_evidence_errors
        )
    else:
        terminal = (root / "manifests/catalog-maintenance-successor-decision-v1.json").is_file()
        report.passes.append(
            "catalog-maintenance-successor-evidence="
            + ("terminal-redacted" if terminal else "pre-output")
        )

    from metis_model1.maintenance_decision import (
        build_blocked_maintenance_contract,
        validate_maintenance_decision,
    )

    try:
        validate_maintenance_decision(build_blocked_maintenance_contract())
    except Exception as error:  # noqa: BLE001 - authority boundary must fail closed
        report.errors.append(f"maintenance-decision: {type(error).__name__}: {error}")
    else:
        report.passes.append("maintenance-decision=protected-authority-required")

    accuracy_uplift_errors = validate_accuracy_uplift_plan_contract(root)
    if accuracy_uplift_errors:
        report.errors.extend(accuracy_uplift_errors)
    else:
        plan_status = load_json(root / "manifests/accuracy-uplift-plan.json")["status"]
        report.passes.append(f"accuracy-uplift=D18/64+16/T30/{plan_status.replace('_', '-')}")

    hyperparameter_errors = validate_hyperparameter_grid_contract(root)
    if hyperparameter_errors:
        report.errors.extend(hyperparameter_errors)
    else:
        report.passes.append("w5-grid=4-screening/3-finalist-seeds/max-700-steps")

    qualification_errors = validate_qualification_contract(root)
    if qualification_errors:
        report.errors.extend(qualification_errors)
    else:
        report.passes.append("qualification=static-contract-pass")

    w1_w2_errors = validate_w1_w2_evidence_package(root)
    if w1_w2_errors:
        report.errors.extend(w1_w2_errors)
    else:
        report.passes.append("w1-w2-evidence-package=6-semantic-sidecars")

    repository_files = git_repository_files(root)
    report.repository_files = len(repository_files)
    policy_errors = validate_artifact_policy_paths(repository_files)
    policy_errors.extend(validate_repository_file_contents(root, repository_files))
    if policy_errors:
        report.errors.extend(policy_errors)
    else:
        report.passes.append(f"artifact-policy=pass files={len(repository_files)}")

    register = load_json(root / "manifests/decision-register.json")
    report.open_by_wave = _collect_wave_blocks(register)
    report.open_nonblocking = _collect_nonblocking_open(register)
    return report
