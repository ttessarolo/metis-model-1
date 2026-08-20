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
)

REQUIRED_FOUNDATION_PATHS = (
    "AGENTS.md",
    "BLACKBOARD.md",
    "Makefile",
    "pyproject.toml",
    "uv.lock",
    "docs/08-orchestration-and-blackboards.md",
    "docs/09-repository-and-artifact-policy.md",
    "docs/10-open-decisions.md",
    "docs/11-feasibility-and-risks.md",
    "docs/12-accuracy-99-execution-plan.md",
    ".orchestra/teams.json",
    "manifests/accuracy-target.json",
    "manifests/artifact-store-policy.json",
    "manifests/hyperparameter-grid.json",
    "manifests/slice-30-assets.json",
    "manifests/slice-30-closure.json",
    "manifests/source-model-revisions.json",
    "manifests/decision-register.json",
    "manifests/benchmark-plan.json",
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
    "qualification/train_full_state.py",
    "qualification/uv.lock",
    "qualification/verify_adapter.py",
    "qualification/verify_checkpoint.py",
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
        != "local_wrapper_optimizer_rng_sampler_global_step_bit_exact_4_vs_2_plus_resume"
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
