"""Sealed, held-out T30 grammar and Metis-standard-library evaluation.

T30 is deliberately a new evaluator rather than a switch on the historical
D18 runner.  It has its own task roster, truth, freeze, attempt receipt and
evidence.  In particular it is *not* a dataset builder, trainer, optimiser or
promotion path.  The only model interaction is the single sealed base pass and
the single sealed adapter pass performed by :func:`run`.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from metis_model1 import catalog_maintenance_pin as catalog_pin
from metis_model1 import demo_accuracy as safe
from metis_model1 import grammar_stdlib_accuracy as d18
from metis_model1 import grammar_stdlib_oracle as oracle
from metis_model1 import initial_local_qlora_backup as backup
from metis_model1 import initial_local_qlora_runtime as qlora
from metis_model1 import initial_local_qlora_train as trainer
from metis_model1.catalog_maintenance_probe import _extract_source

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASKS_PATH = PROJECT_ROOT / "fixtures/grammar-stdlib-accuracy-v1/t30-tasks.json"
REFERENCE_PATH = PROJECT_ROOT / "fixtures/grammar-stdlib-accuracy-v1/t30-reference-context.md"
POLICY_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-policy-v1.json"
TRUTH_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-truth-v1.json"
FREEZE_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-freeze-v1.json"
EVIDENCE_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-evaluation-v1.json"
ADJUDICATION_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-adjudication-v1.json"
RUN_ROOT = PROJECT_ROOT / "artifacts/grammar-stdlib-accuracy/t30"
RUN_ID = "t30-v1-20260825"
RUN_RELATIVE = f"artifacts/grammar-stdlib-accuracy/t30/{RUN_ID}"
ATTEMPT_NONCE = "gsl-t30-v1-20260825-attempt-01"
ADAPTER_PATH = PROJECT_ROOT / "artifacts/initial-local-qlora-v1/run-v2/checkpoints/step-00000050"
DATASET_RECEIPT_PATH = PROJECT_ROOT / "artifacts/initial-local-qlora-v1/dataset/receipt.json"
BACKUP_PREIMAGE_PATH = PROJECT_ROOT / "manifests/initial-local-qlora-backup-preimage-v1.json"
PACKAGE_DIR = qlora.DEFAULT_OUTPUT_ROOT / "package"
ARCHIVE_PATH = qlora.DEFAULT_OUTPUT_ROOT / "metis-model1-adapter.tar"
ARCHIVE_RECEIPT_PATH = qlora.DEFAULT_OUTPUT_ROOT / "metis-model1-adapter-archive.json"
BACKUP_RECEIPT_PATH = qlora.DEFAULT_OUTPUT_ROOT / "metis-model1-adapter-backup-receipt.json"
B12_RECEIPT_PATH = qlora.DEFAULT_OUTPUT_ROOT / "b12-adapter/receipt.json"
PACKAGE_LIVE_MEMBERS = {
    "dataset-receipt.json": DATASET_RECEIPT_PATH,
    "training-receipt.json": qlora.DEFAULT_TRAINING_RECEIPT,
    "selection-receipt.json": qlora.DEFAULT_SELECTION_RECEIPT,
    "evaluation-receipt.json": B12_RECEIPT_PATH,
    "restore-receipt.json": qlora.DEFAULT_RESTORE_RECEIPT,
    "adapter_config.json": ADAPTER_PATH / "adapter_config.json",
    "adapters.safetensors": ADAPTER_PATH / "adapters.safetensors",
    "runtime.lock": PROJECT_ROOT / "qualification/uv.lock",
}
DEFAULT_METIS_ROOT = d18.DEFAULT_METIS_ROOT
DEFAULT_NODE = d18.DEFAULT_NODE
QUALIFICATION_PYTHON = d18.QUALIFICATION_PYTHON
BENCHMARK_ID = "grammar-stdlib-accuracy-t30-v1"
POLICY_ID = "grammar-stdlib-accuracy-t30-policy/v1"
TRUTH_ID = "grammar-stdlib-accuracy-t30-truth/v1"
FREEZE_ID = "grammar-stdlib-accuracy-t30-freeze/v1"
EVIDENCE_ID = "grammar-stdlib-accuracy-t30-evaluation/v1"
ADJUDICATION_ID = "grammar-stdlib-accuracy-t30-adjudication/v1"
HUMAN_REVIEW_ID = "grammar-stdlib-accuracy-t30-human-review/v1"
ROSTER_ID = "gsl_t30_public_synthetic_v1"
PROVENANCE_NAMESPACE = "gsl_t30"
TASK_ID_PREFIX = "gsl_t30_"
FRESHNESS_NAMESPACE = b"gsl_t30"
PRE_REVIEW_VERDICT = "GRAMMAR_STDLIB_T30_REVIEW_REQUIRED"
PASS_VERDICT = "GRAMMAR_STDLIB_T30_PASS_NO_RETRAIN"
DIAGNOSE_VERDICT = "GRAMMAR_STDLIB_T30_DIAGNOSE"
F4_REVIEW_CONTRACT = d18.SEMANTIC_SIGNATURE_CONTRACT
F6_REVIEW_CONTRACT = "metis-structural-explanation/v1"
TASK_COUNT = 30
TASKS_PER_FAMILY = 5
HUMAN_REVIEW_COUNT = 15
FAMILIES = tuple(f"F-{number}" for number in range(1, 7))
TOP_LEVELS = d18.TOP_LEVELS
STDLIB_MEMBERS = d18.STDLIB_MEMBERS
STDLIB_SETTINGS = d18.STDLIB_SETTINGS
STDLIB_MODULES: set[str] = set()
INTERACTION_CLASSES: set[str] = set()
COVERAGE_FIELDS = ("top_levels", "stdlib_members", "stdlib_settings")
MODEL_JSON_COVERAGE_FIELDS = ("top_levels", "stdlib_members", "stdlib_settings")
F4_ENDPOINT_SHAPE = "legacy_optional_variant"
F6_ALWAYS_CATALOG_FIELDS = False
CATALOG_INLINE_DOMAIN_SUPPORTED = False
REQUIRE_CATALOG_DOMAIN_SIZE = False
STRUCTURAL_FIRST_USE_DEDUP = False
REQUIRE_EXACT_REVIEW_CONTRACT = False
# V1 predates the explicit surface/serialization contract.  The successor
# enables this switch without retroactively changing its terminal evidence.
KNOWN_SURFACE_ALIASES_ARE_CONTRACT_MISMATCH = False
CLASSIFY_SOURCE_SYMBOL_FAILURES = False
CONTRACT_MISMATCH_FAILURE_CODE = "json_contract_mismatch"
# Successors may bind earlier terminal evidence and include its task/truth
# material in the freshness denominator.  Empty defaults preserve V1 exactly.
PREDECESSOR_TERMINAL_EVALUATION: dict[str, Any] | None = None
ADDITIONAL_FRESHNESS_TASK_PATHS: tuple[Path, ...] = ()
ADDITIONAL_FRESHNESS_TRUTH_PATHS: tuple[Path, ...] = ()
RELATIONSHIP_LABELS = {
    "settings-configures-timezone",
    "endpoint-declares-needs-time",
    "property-declares-needs-time",
    "pure-stdlib-call",
    "no-ambient-needs",
    "valueset-belongs-to-catalog",
    "endpoint-owns-block",
    "variant-selects-block",
    "external-enum-domain",
}
GENERATION = {"temperature": 0, "seed": 17, "thinking": False, "max_tokens": 512}
THRESHOLDS = {
    "adapter_semantic_total_min": 29,
    "semantic_denominator": 30,
    "family_semantic_min": 4,
    "automatic_semantic_total_min": 19,
    "automatic_semantic_denominator": 20,
    "automatic_family_min": 4,
    "critical_max": 0,
    "adapter_regression_allowed": False,
}
TASK_MODES = {"source_output", "exact_json_review"}
TASK_TIERS = {
    "F-1": "pinned_oracle_required",
    "F-2": "pinned_oracle_required",
    "F-3": "pinned_oracle_required",
    "F-4": "pinned_review_oracle_required",
    "F-5": "human_review_required",
    "F-6": "human_review_required",
}
TASK_KINDS = {
    "F-1": "author_source",
    "F-2": "minimal_edit_source",
    "F-3": "diagnostic_repair",
    "F-4": "semantic_review",
    "F-5": "migration_source",
    "F-6": "structural_explanation",
}
TASK_FAMILY_MODES = {
    "F-1": "source_output",
    "F-2": "source_output",
    "F-3": "source_output",
    "F-4": "exact_json_review",
    "F-5": "source_output",
    "F-6": "exact_json_review",
}
# F2 remains an automatic semantic task, but minimality remains a separate
# human judgement.  F5/F6 likewise cannot complete the final T30 verdict
# without their named review even when their mechanical comparison matches.
FINAL_HUMAN_REVIEW = {
    "F-2": "patch_minimality_required",
    "F-5": "migration_minimality_required",
    "F-6": "structural_explanation_required",
}
NONCLAIMS = [
    "not_accuracy99",
    "not_population_accuracy",
    "not_tenant_or_live_data_accuracy",
    "not_training_data",
    "no_training_authority",
    "no_delta_qlora_authority",
    "no_dataset_authority",
    "no_promotion_authority",
    "no_companion_vscode_or_windows_claim",
]
POLICY_ROSTER = {
    "tasks": TASK_COUNT,
    "tasks_per_family": TASKS_PER_FAMILY,
    "automatic_tasks": 20,
    "human_review_task_ids_expected": HUMAN_REVIEW_COUNT,
    "human_review_families": ["F-2", "F-5", "F-6"],
    "top_levels_required": 10,
    "stdlib_members_required": 12,
    "stdlib_settings_required": 1,
    "rare_or_critical_construct_min_occurrences": 2,
    "catalog_domain_family_reservations": ["F-1", "F-6"],
}
POLICY_COVERAGE_GATE = {
    "credit_source": "final_successful_tasks_only",
    "declared_metadata_alone_is_ineligible": True,
    "top_levels": "all_10",
    "stdlib_members": "all_12",
    "stdlib_settings": ["time.timezone"],
}
POLICY_EXTRA_CONTRACT: dict[str, Any] = {}
FINAL_COVERAGE_GATE_NAMES = {
    "top_levels": "coverage_all_10_top_levels",
    "stdlib_members": "coverage_all_12_stdlib_members",
    "stdlib_settings": "coverage_time_timezone",
}
REFERENCE_HEADING = "# Metis 0.43 grammar and standard-library reference\n"
REFERENCE_REQUIRED_MARKERS = {
    "tenant sample.world",
    "catalog sample.video",
    "property sample.policy",
    "endpoint sample.feed",
    "preset sample.recent",
    "list sample.labels",
    "transformer sample.slug",
    "block sample_card",
    "settings sample.time",
    "values sample.video",
    "time.now",
    "time.month",
    "time.day",
    "time.hour",
    "time.hhmm",
    "time.fractional_second",
    "time.weekday",
    "time.timezone",
    "std.codec.decode",
    "std.codec.encode",
    "std.text.slugify",
    "std.text.truncate",
    "std.text.normalize",
    "keyword enum(N)",
    "keyword open",
    "variant <variant> use block.<block>",
}
REFERENCE_FORBIDDEN_MARKERS = {"gsl_d18", "play-prod", "play-demo"}
REFERENCE_PROVENANCE_MARKER = "not tenant data and not a training example"
# Explicitly includes the T30 implementation so code drift invalidates its seal.
BOUND_PATHS = (
    "fixtures/grammar-stdlib-accuracy-v1/t30-tasks.json",
    "fixtures/grammar-stdlib-accuracy-v1/t30-reference-context.md",
    "manifests/grammar-stdlib-accuracy-t30-policy-v1.json",
    "manifests/grammar-stdlib-accuracy-t30-truth-v1.json",
    "manifests/initial-local-qlora-backup-preimage-v1.json",
    "manifests/catalog-maintenance-pin-v1.json",
    "manifests/grammar-stdlib-pin-v1.json",
    "src/metis_model1/grammar_stdlib_t30.py",
    "src/metis_model1/demo_accuracy.py",
    "src/metis_model1/grammar_stdlib_accuracy.py",
    "src/metis_model1/grammar_stdlib_oracle.py",
    "src/metis_model1/grammar_stdlib_coverage.py",
    "src/metis_model1/initial_local_qlora_backup.py",
    "src/metis_model1/initial_local_qlora_runtime.py",
    "src/metis_model1/initial_local_qlora_train.py",
    "src/metis_model1/catalog_maintenance_pin.py",
    "src/metis_model1/catalog_maintenance_probe.py",
    "src/metis_model1/catalog_retrieval.py",
    "src/metis_model1/catalog_retrieval_refresh.py",
    "src/metis_model1/oracles.py",
    "runtime/metis_oracle/runner.ts",
    "runtime/metis_oracle/native_ts_loader.mjs",
    "schemas/catalog-maintenance-pin.schema.json",
    "qualification/checkpoint-pin.json",
    "qualification/runtime-pin.json",
    "qualification/uv.lock",
)


class GrammarStdlibT30Error(RuntimeError):
    """The held-out T30 contract cannot be established."""


def canonical_hash(value: Any) -> str:
    return safe.canonical_hash(value)


def raw_hash(raw: bytes) -> str:
    return safe.raw_hash(raw)


def _load(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        return d18._load(path, label)
    except d18.GrammarStdlibAccuracyError as error:
        raise GrammarStdlibT30Error(str(error)) from error


def _self_hash(value: Mapping[str, Any], field: str) -> None:
    if value.get(field) != canonical_hash(
        {key: item for key, item in value.items() if key != field}
    ):
        raise GrammarStdlibT30Error(f"{field} does not match canonical body")


def _policy() -> tuple[dict[str, Any], bytes]:
    """Read the independently ratified T30 policy without making it mutable."""

    value, raw = _load(POLICY_PATH, "T30 policy")
    _self_hash(value, "policy_sha256")
    expected = {
        "schema_version": 1,
        "policy_id": POLICY_ID,
        "status": "ratified_before_t30_model_output",
        "benchmark_id": BENCHMARK_ID,
    }
    if any(value.get(key) != item for key, item in expected.items()):
        raise GrammarStdlibT30Error("ratified T30 policy identity drift")
    if value.get("nonclaims") != NONCLAIMS:
        raise GrammarStdlibT30Error("ratified T30 policy nonclaims drift")
    if any(
        value.get(key) is not False
        for key in ("model_outputs_observed", "training_authorized", "delta_qlora_authorized")
    ):
        raise GrammarStdlibT30Error("ratified T30 policy authority drift")
    if value.get("roster") != POLICY_ROSTER:
        raise GrammarStdlibT30Error("ratified T30 roster policy drift")
    if value.get("automatic_gate") != {
        "adapter_semantic_min": THRESHOLDS["automatic_semantic_total_min"],
        "denominator": THRESHOLDS["automatic_semantic_denominator"],
        "family_min": THRESHOLDS["automatic_family_min"],
        "family_denominator": 5,
        "families": ["F-1", "F-2", "F-3", "F-4"],
        "critical_max": THRESHOLDS["critical_max"],
        "paired_regressions_max": 0,
    }:
        raise GrammarStdlibT30Error("ratified T30 automatic gate drift")
    if value.get("final_gate") != {
        "adapter_semantic_min": THRESHOLDS["adapter_semantic_total_min"],
        "denominator": THRESHOLDS["semantic_denominator"],
        "family_min": THRESHOLDS["family_semantic_min"],
        "family_denominator": 5,
        "critical_max": THRESHOLDS["critical_max"],
        "invented_symbol_max": 0,
        "unauthorized_write_max": 0,
        "retrieval_or_truth_failure_max": 0,
        "tool_failure_max": 0,
        "paired_regressions_max": 0,
        "adapter_off_restore_required": True,
        "final_success": {
            "F-1": ["automatic_semantic_correct"],
            "F-2": ["automatic_semantic_correct", "patch_minimality_accept"],
            "F-3": ["automatic_semantic_correct"],
            "F-4": ["automatic_semantic_correct"],
            "F-5": ["oracle_mechanical_match", "migration_minimality_accept"],
            "F-6": ["json_mechanical_match", "structural_explanation_accept"],
        },
    }:
        raise GrammarStdlibT30Error("ratified T30 final gate drift")
    if value.get("coverage_gate") != POLICY_COVERAGE_GATE:
        raise GrammarStdlibT30Error("ratified T30 coverage gate drift")
    if any(value.get(key) != item for key, item in POLICY_EXTRA_CONTRACT.items()):
        raise GrammarStdlibT30Error("ratified T30 successor contract drift")
    if value.get("decision_policy") != {
        "pre_review_verdict": PRE_REVIEW_VERDICT,
        "passing_verdict": PASS_VERDICT,
        "failing_verdict": DIAGNOSE_VERDICT,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "dataset_authorized": False,
        "promotion_authorized": False,
    }:
        raise GrammarStdlibT30Error("ratified T30 decision policy drift")
    one_shot = value.get("one_shot")
    if one_shot != {
        "attempts": 1,
        "worker_invocations": 2,
        "requests_per_worker": TASK_COUNT,
        "retries": 0,
        "fixed_run_id": RUN_ID,
        "attempt_nonce": ATTEMPT_NONCE,
        "partial_outputs_preserved": True,
        "partial_run_disposition": "permanent_stop_no_recovery_no_retry",
        "preexisting_run_or_attempt_is_stop": True,
        "local_threat_model": "cooperative_no_host_rollback_attestation",
    }:
        raise GrammarStdlibT30Error("ratified T30 attempt nonce drift")
    taxonomy = value.get("taxonomy")
    if (
        not isinstance(taxonomy, Mapping)
        or taxonomy.get("authority") != "global_metis_family_taxonomy"
    ):
        raise GrammarStdlibT30Error("ratified T30 taxonomy drift")
    families = taxonomy.get("families")
    if not isinstance(families, Mapping) or set(families) != set(FAMILIES):
        raise GrammarStdlibT30Error("ratified T30 family taxonomy drift")
    for family in FAMILIES:
        declared = families[family]
        if (
            not isinstance(declared, Mapping)
            or declared.get("kind") != TASK_KINDS[family]
            or declared.get("task_mode") != TASK_FAMILY_MODES[family]
            or declared.get("automatic_authority")
            != (TASK_TIERS[family] if family not in {"F-5", "F-6"} else None)
            or declared.get("secondary_human_review") != FINAL_HUMAN_REVIEW.get(family)
        ):
            raise GrammarStdlibT30Error("ratified T30 family contract drift")
    return value, raw


def _task_keys(task: Mapping[str, Any]) -> set[str]:
    keys = {
        "task_id",
        "family",
        "kind",
        "task_mode",
        "authority_tier",
        "prompt",
        "oracle",
        "coverage",
        "provenance_roots",
        "model_outputs_observed",
        "training_input_allowed",
        "delta_qlora_input_allowed",
        "training_label_eligible",
    }
    for field in (
        "input_source",
        "before_source",
        "expected_source",
        "expected_repaired_source",
    ):
        if field in task:
            keys.add(field)
    if task.get("task_mode") == "exact_json_review":
        keys.add("expected_json")
    return keys


def _coverage_domains() -> dict[str, set[str]]:
    domains = {
        "top_levels": TOP_LEVELS,
        "stdlib_members": STDLIB_MEMBERS,
        "stdlib_settings": STDLIB_SETTINGS,
        "stdlib_modules": STDLIB_MODULES,
        "interaction_classes": INTERACTION_CLASSES,
    }
    if len(COVERAGE_FIELDS) != len(set(COVERAGE_FIELDS)) or any(
        field not in domains for field in COVERAGE_FIELDS
    ):
        raise GrammarStdlibT30Error("T30 coverage-field configuration drift")
    return {field: domains[field] for field in COVERAGE_FIELDS}


def _empty_coverage() -> dict[str, list[str]]:
    return {field: [] for field in COVERAGE_FIELDS}


def _declared_interaction_classes(task: Mapping[str, Any]) -> list[str]:
    if "interaction_classes" not in COVERAGE_FIELDS:
        return []
    coverage = task.get("coverage")
    if not isinstance(coverage, Mapping):
        raise GrammarStdlibT30Error("T30 interaction coverage is unavailable")
    values = coverage.get("interaction_classes")
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise GrammarStdlibT30Error("T30 interaction coverage is invalid")
    return list(values)


def _scenario_interactions(task: Mapping[str, Any]) -> set[str]:
    """Derive model-facing stdlib boundary scenarios from sealed task sources.

    Interaction coverage is not an AST declaration census: several scenarios
    deliberately begin with invalid or warning-only source.  The task earns the
    declared scenario only after its candidate succeeds, but preregistration
    must first prove that the scenario is present in the frozen input/target.
    """

    before = str(task.get("before_source", ""))
    valid = "\n".join(
        str(task[field])
        for field in ("input_source", "expected_source", "expected_repaired_source")
        if isinstance(task.get(field), str)
    )
    allowed_members = {tuple(member.split(".", 1)) for member in STDLIB_MEMBERS if "." in member}
    valid_time = re.search(r"(?<!std\.)\btime\.[A-Za-z_][A-Za-z0-9_]*\b", valid)
    before_time = re.search(r"(?<!std\.)\btime\.[A-Za-z_][A-Za-z0-9_]*\b", before)
    valid_pure = re.search(r"\bstd\.(?:codec|text)\.[A-Za-z_][A-Za-z0-9_]*\b", valid)
    result: set[str] = set()
    if valid_time and re.search(r"\bneeds\s+time\b", valid):
        result.add("ambient-valid-needs-time")
    if re.search(r"\bstd\.time\.[A-Za-z_][A-Za-z0-9_]*\b", before):
        result.add("ambient-invalid-std-namespace")
    if before_time and not re.search(r"\bneeds\s+time\b", before):
        result.add("ambient-missing-needs")
    if valid_pure and not re.search(r"\bneeds\s+(?:codec|text)\b", valid):
        result.add("pure-valid-no-needs")
    if re.search(r"\bneeds\s+(?:codec|text)\b", before):
        result.add("pure-invalid-needs")
    modules = re.findall(r"\bstd\.([A-Za-z_][A-Za-z0-9_]*)\.", before)
    if any(module not in {"time", "codec", "text"} for module in modules):
        result.add("unknown-stdlib-module")
    references = re.findall(r"\b(?:std\.)?(time|codec|text)\.([A-Za-z_][A-Za-z0-9_]*)\b", before)
    if any((module, member) not in allowed_members for module, member in references):
        result.add("unknown-stdlib-member")
    needs = re.findall(r"\bneeds\s+([A-Za-z_][A-Za-z0-9_]*)\b", before)
    if any(capability not in {"time", "codec", "text"} for capability in needs):
        result.add("unknown-needs-capability")
    if re.search(r"\bsettings\s+[^\s{]+\.time\s*\{[^}]*\btimezone\b", valid, re.S):
        result.add("timezone-setting-valid")
    if re.search(r"\bsettings\s+[^\s{]+\.time\s*\{", before) and not re.search(
        r"\btimezone\b", before
    ):
        result.add("timezone-setting-invalid-key")
    return result


def _validate_interaction_coverage(task: Mapping[str, Any]) -> None:
    declared = set(_declared_interaction_classes(task))
    missing = declared - _scenario_interactions(task)
    if missing:
        raise GrammarStdlibT30Error(
            f"T30 interaction coverage has no source scenario: {sorted(missing)[0]}"
        )


def validate_tasks(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate exactly five independently rooted held-out tasks per family."""

    if set(manifest) != {
        "schema_version",
        "roster_id",
        "policy_id",
        "benchmark_id",
        "provenance",
        "tasks",
    }:
        raise GrammarStdlibT30Error("T30 roster field set differs from fixed contract")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("roster_id") != ROSTER_ID
        or manifest.get("policy_id") != POLICY_ID
        or manifest.get("benchmark_id") != BENCHMARK_ID
    ):
        raise GrammarStdlibT30Error("T30 roster identity differs from fixed contract")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping) or provenance != {
        "kind": "public_synthetic",
        "namespace": PROVENANCE_NAMESPACE,
        "pin_revision": "5e112f9148f40e7e792052e896c5a9efe8eaf0a2",
        "language_version": "0.43",
        "source_validation": "pinned_oracle_required_before_truth",
        "model_outputs_observed": False,
        "training_input_allowed": False,
        "delta_qlora_input_allowed": False,
    }:
        raise GrammarStdlibT30Error("T30 roster provenance is not pre-output public synthetic")
    rows = manifest.get("tasks")
    if not isinstance(rows, list) or len(rows) != TASK_COUNT:
        raise GrammarStdlibT30Error("T30 roster must contain exactly thirty tasks")
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    roots: set[str] = set()
    templates: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != _task_keys(row):
            raise GrammarStdlibT30Error("T30 task fields differ from fixed contract")
        task_id, family = row.get("task_id"), row.get("family")
        if (
            not isinstance(task_id, str)
            or not task_id.startswith(TASK_ID_PREFIX)
            or task_id in ids
            or family not in FAMILIES
            or row.get("kind") != TASK_KINDS[family]
            or row.get("task_mode") != TASK_FAMILY_MODES[family]
            or row.get("authority_tier") != TASK_TIERS[family]
            or not isinstance(row.get("prompt"), str)
            or not row["prompt"]
            or row.get("model_outputs_observed") is not False
            or row.get("training_input_allowed") is not False
            or row.get("delta_qlora_input_allowed") is not False
            or row.get("training_label_eligible") is not False
        ):
            raise GrammarStdlibT30Error("T30 task identity/taxonomy is invalid")
        if row["task_mode"] == "exact_json_review" and (
            not isinstance(row.get("expected_json"), dict) or not row["expected_json"]
        ):
            raise GrammarStdlibT30Error("T30 expected target is invalid")
        if row["task_mode"] == "source_output" and not any(
            isinstance(row.get(field), str) and row[field]
            for field in ("expected_source", "expected_repaired_source")
        ):
            raise GrammarStdlibT30Error("T30 expected target is invalid")
        for field in (
            "input_source",
            "before_source",
            "expected_source",
            "expected_repaired_source",
        ):
            if field in row and (
                not isinstance(row[field], str) or not row[field].startswith("metis 0.43\n")
            ):
                raise GrammarStdlibT30Error(f"T30 {field} is invalid")
        specification = row.get("oracle")
        if not isinstance(specification, Mapping) or specification.get("mode") not in {
            "source",
            "endpoint",
        }:
            raise GrammarStdlibT30Error("T30 oracle specification is invalid")
        if specification.get("input_status") != "pinned_oracle_required_before_truth":
            raise GrammarStdlibT30Error("T30 oracle is not pinned")
        if (
            REQUIRE_EXACT_REVIEW_CONTRACT
            and family in {"F-4", "F-6"}
            and (
                specification.get("exact_contract")
                != (F4_REVIEW_CONTRACT if family == "F-4" else F6_REVIEW_CONTRACT)
            )
        ):
            raise GrammarStdlibT30Error("T30 exact review contract is not pinned")
        coverage, provenance_roots = row.get("coverage"), row.get("provenance_roots")
        coverage_domains = _coverage_domains()
        if (
            not isinstance(coverage, Mapping)
            or set(coverage) != set(COVERAGE_FIELDS)
            or not all(isinstance(coverage.get(key), list) for key in COVERAGE_FIELDS)
            or any(
                any(not isinstance(item, str) for item in coverage[key])
                or len(coverage[key]) != len(set(coverage[key]))
                or not set(coverage[key]).issubset(allowed)
                for key, allowed in coverage_domains.items()
            )
            or not isinstance(provenance_roots, Mapping)
            or set(provenance_roots) != {"independent", "template"}
            or not all(
                isinstance(value, str) and value.startswith(PROVENANCE_NAMESPACE)
                for value in provenance_roots.values()
            )
            or provenance_roots["independent"] == provenance_roots["template"]
        ):
            raise GrammarStdlibT30Error("T30 coverage or provenance roots are invalid")
        _validate_interaction_coverage(row)
        if "timezone-setting-invalid-key" in _declared_interaction_classes(row) and (
            not isinstance(row.get("before_source"), str)
            or not isinstance(row.get("expected_repaired_source"), str)
            or specification.get("input_failure_kind") is not None
            or not isinstance(specification.get("diagnostic_substrings"), list)
            or not specification["diagnostic_substrings"]
            or any(
                not isinstance(marker, str) or not marker
                for marker in specification["diagnostic_substrings"]
            )
        ):
            raise GrammarStdlibT30Error("T30 warning-only timezone repair contract is invalid")
        ids.add(task_id)
        roots.add(str(provenance_roots["independent"]))
        templates.add(str(provenance_roots["template"]))
        result.append(dict(row))
    if Counter(item["family"] for item in result) != Counter(
        {family: TASKS_PER_FAMILY for family in FAMILIES}
    ):
        raise GrammarStdlibT30Error("T30 family census must be exactly five per family")
    if roots & templates or len(roots) != TASK_COUNT or len(templates) != TASK_COUNT:
        raise GrammarStdlibT30Error("T30 provenance roots are not globally disjoint")
    for field, denominator in _coverage_domains().items():
        if {value for task in result for value in task["coverage"][field]} != denominator:
            raise GrammarStdlibT30Error(f"T30 {field} denominator drift")
    return result


def load_tasks() -> tuple[dict[str, Any], list[dict[str, Any]], bytes]:
    manifest, raw = _load(TASKS_PATH, "T30 tasks")
    return manifest, validate_tasks(manifest), raw


def _reference_context() -> tuple[str, bytes]:
    raw = safe._read_regular(REFERENCE_PATH, "T30 reference context", 64 * 1024)
    try:
        reference = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GrammarStdlibT30Error("T30 reference context is not UTF-8") from error
    if (
        not reference.startswith(REFERENCE_HEADING)
        or any(marker not in reference for marker in REFERENCE_REQUIRED_MARKERS)
        or any(marker in reference for marker in REFERENCE_FORBIDDEN_MARKERS)
        or REFERENCE_PROVENANCE_MARKER not in reference
    ):
        raise GrammarStdlibT30Error("T30 reference context drift or D18 contamination")
    return reference, raw


def _messages_with_reference(task: Mapping[str, Any], reference: str) -> list[dict[str, str]]:
    text = str(task["prompt"])
    source = task.get("input_source", task.get("before_source"))
    if source is not None:
        text += "\n\nCurrent Metis source:\n" + str(source).rstrip()
    system = "Return exactly one complete Metis 0.43 source, with no prose."
    if task["task_mode"] == "exact_json_review":
        system = "Return exactly one JSON object, with no prose or markdown."
    return [
        {
            "role": "system",
            "content": system + "\n\nRetrieved pinned reference:\n" + reference.rstrip(),
        },
        {"role": "user", "content": text},
    ]


def build_messages(task: Mapping[str, Any]) -> list[dict[str, str]]:
    reference, _raw = _reference_context()
    return _messages_with_reference(task, reference)


def _request_batch(tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    reference, _raw = _reference_context()
    return [
        {
            "request_id": task["task_id"],
            "messages": _messages_with_reference(task, reference),
            "max_tokens": GENERATION["max_tokens"],
        }
        for task in tasks
    ]


def _oracle_signature(
    task: Mapping[str, Any],
    source: str,
    metis_root: Path,
    node_path: Path,
    session: oracle.GrammarStdlibOracleSession,
) -> dict[str, Any]:
    try:
        return d18._oracle_signature(
            d18._oracle_task(task, source, metis_root, node_path, session=session), task
        )
    except d18.GrammarStdlibAccuracyError as error:
        raise GrammarStdlibT30Error(str(error)) from error


def _validate_source(
    task: Mapping[str, Any],
    source: str,
    metis_root: Path,
    node_path: Path,
    session: oracle.GrammarStdlibOracleSession,
    *,
    expected_ok: bool,
) -> dict[str, Any]:
    signature, _envelope = _validate_source_envelope(
        task,
        source,
        metis_root,
        node_path,
        session,
        expected_ok=expected_ok,
    )
    return signature


def _validate_source_envelope(
    task: Mapping[str, Any],
    source: str,
    metis_root: Path,
    node_path: Path,
    session: oracle.GrammarStdlibOracleSession,
    *,
    expected_ok: bool,
    expected_diagnostic_markers: tuple[str, ...] = (),
    require_no_diagnostics: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate once and retain the pinned AST needed by review/coverage truth."""

    try:
        envelope = d18._oracle_task(task, source, metis_root, node_path, session=session)
        result = envelope["result"]
        if expected_ok:
            if result["status"] != "ok":
                raise GrammarStdlibT30Error(f"expected input rejected by oracle: {task['task_id']}")
            diagnostics = d18._diagnostic_text(envelope)
            missing = [
                marker
                for marker in expected_diagnostic_markers
                if not any(marker in text for text in diagnostics)
            ]
            if missing:
                raise GrammarStdlibT30Error(
                    f"expected warning marker is absent for {task['task_id']}"
                )
            if require_no_diagnostics and diagnostics:
                raise GrammarStdlibT30Error(
                    f"expected repaired source retains diagnostics: {task['task_id']}"
                )
        else:
            if result["status"] != "invalid":
                raise GrammarStdlibT30Error(f"invalid input accepted by oracle: {task['task_id']}")
            diagnostics = d18._diagnostic_text(envelope)
            missing = [
                marker
                for marker in task["oracle"]["diagnostic_substrings"]
                if not any(marker in text for text in diagnostics)
            ]
            expected_kind = task["oracle"]["input_failure_kind"]
            if (
                missing
                or not isinstance(expected_kind, str)
                or not result["diagnostics"].get(expected_kind)
            ):
                raise GrammarStdlibT30Error(
                    f"oracle failure contract mismatch for {task['task_id']}"
                )
        return d18._oracle_signature(envelope, task), envelope
    except d18.GrammarStdlibAccuracyError as error:
        raise GrammarStdlibT30Error(str(error)) from error


def _ast_nodes(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, list):
        for item in value:
            yield from _ast_nodes(item)
        return
    if not isinstance(value, Mapping):
        return
    if isinstance(value.get("$type"), str):
        yield value
    for key, item in value.items():
        if isinstance(key, str) and not key.startswith(("$", "_")) and key != "ref":
            yield from _ast_nodes(item)


def _unique(values: Iterator[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _structural_first_use(values: list[Any]) -> list[Any]:
    """Deduplicate exact structural records only for contracts that require it."""

    if not STRUCTURAL_FIRST_USE_DEDUP:
        return values
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        identity = canonical_hash(value)
        if identity not in seen:
            seen.add(identity)
            result.append(value)
    return result


def _coverage_from_inventory(inventory: Any) -> dict[str, list[str]]:
    nodes = list(_ast_nodes(inventory))
    top_levels = _unique(
        str(node["$type"]) for node in nodes if str(node.get("$type")) in TOP_LEVELS
    )
    members = _unique(
        (
            f"time.{node['member']}"
            if node.get("$type") == "TimeRef"
            else f"{node['module']}.{node['member']}"
        )
        for node in nodes
        if (
            node.get("$type") == "TimeRef"
            and isinstance(node.get("member"), str)
            and f"time.{node['member']}" in STDLIB_MEMBERS
        )
        or (
            node.get("$type") == "StdCall"
            and isinstance(node.get("module"), str)
            and isinstance(node.get("member"), str)
            and f"{node['module']}.{node['member']}" in STDLIB_MEMBERS
        )
    )
    settings = []
    for node in nodes:
        if node.get("$type") != "SettingsDecl" or not str(node.get("name", "")).endswith(".time"):
            continue
        if any(
            child.get("$type") == "SettingsPair" and child.get("key") == "timezone"
            for child in _ast_nodes(node)
        ):
            settings.append("time.timezone")
    modules = _unique(member.split(".", 1)[0] for member in members)
    if settings and "time" not in modules:
        modules.append("time")
    base = {
        "top_levels": top_levels,
        "stdlib_members": members,
        "stdlib_settings": list(dict.fromkeys(settings)),
        "stdlib_modules": modules,
        "interaction_classes": [],
    }
    result = {field: base[field] for field in COVERAGE_FIELDS}
    if any(
        not set(result[field]).issubset(allowed) for field, allowed in _coverage_domains().items()
    ):
        raise GrammarStdlibT30Error("pinned AST coverage escaped the T30 denominator")
    return result


def _coverage_for_task(task: Mapping[str, Any], inventory: Any) -> dict[str, list[str]]:
    result = _coverage_from_inventory(inventory)
    if "interaction_classes" in COVERAGE_FIELDS:
        result["interaction_classes"] = _declared_interaction_classes(task)
    return result


def _declarations_from_inventory(inventory: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for node in _ast_nodes(inventory):
        kind = str(node.get("$type"))
        if kind not in TOP_LEVELS:
            continue
        name = node.get("catalog") if kind == "ValueSet" else node.get("name")
        if not isinstance(name, str) or not name:
            raise GrammarStdlibT30Error("pinned AST declaration identity is unavailable")
        result.append({"kind": kind, "name": name})
    return _structural_first_use(result)


def _contains_node(node: Mapping[str, Any], kind: str, **fields: Any) -> bool:
    return any(
        child.get("$type") == kind and all(child.get(key) == value for key, value in fields.items())
        for child in _ast_nodes(node)
    )


def _relationships_from_inventory(inventory: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    elements = inventory.get("elements")
    if not isinstance(elements, list):
        raise GrammarStdlibT30Error("pinned AST element roster is unavailable")
    for element in elements:
        if not isinstance(element, Mapping):
            raise GrammarStdlibT30Error("pinned AST element is invalid")
        kind = element.get("$type")
        if (
            kind == "SettingsDecl"
            and str(element.get("name", "")).endswith(".time")
            and _contains_node(element, "SettingsPair", key="timezone")
        ):
            values.append("settings-configures-timezone")
        if kind == "Catalog" and _contains_node(element, "EnumMarker"):
            values.append("external-enum-domain")
        if kind == "ValueSet":
            values.append("valueset-belongs-to-catalog")
        if kind == "Property" and any(
            child.get("$type") == "NeedsDecl" and "time" in child.get("modules", [])
            for child in _ast_nodes(element)
        ):
            values.append("property-declares-needs-time")
        if kind == "Transformer" and _contains_node(element, "StdCall"):
            values.append("pure-stdlib-call")
            if not _contains_node(element, "TimeRef") and not _contains_node(element, "NeedsDecl"):
                values.append("no-ambient-needs")
        if kind == "Endpoint":
            needs_time = any(
                child.get("$type") == "NeedsDecl" and "time" in child.get("modules", [])
                for child in _ast_nodes(element)
            )
            if needs_time:
                values.append("endpoint-declares-needs-time")
            if _contains_node(element, "NamedBlock"):
                values.append("endpoint-owns-block")
            if _contains_node(element, "VariantDecl") and _contains_node(element, "UseBlock"):
                values.append("variant-selects-block")
    return list(dict.fromkeys(values))


def _catalog_fields(inventory: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for node in _ast_nodes(inventory):
        if node.get("$type") != "Field":
            continue
        name = node.get("name")
        if not isinstance(name, str) or not name:
            raise GrammarStdlibT30Error("catalog field name is unavailable")
        marker = node.get("values")
        if marker is None:
            result.append({"name": name, "domain": "implicit"})
        elif isinstance(marker, Mapping) and marker.get("$type") == "EnumMarker":
            size = marker.get("size")
            if REQUIRE_CATALOG_DOMAIN_SIZE and (
                not isinstance(size, int) or isinstance(size, bool) or size < 0
            ):
                raise GrammarStdlibT30Error("catalog enum size is outside the structural contract")
            result.append({"name": name, "domain": "external-enum", "size": size})
        elif isinstance(marker, Mapping) and marker.get("$type") == "OpenMarker":
            result.append({"name": name, "domain": "open"})
        elif (
            CATALOG_INLINE_DOMAIN_SUPPORTED
            and isinstance(marker, Mapping)
            and marker.get("$type") == "InlineValues"
            and isinstance(marker.get("items"), list)
        ):
            result.append({"name": name, "domain": "inline", "size": len(marker["items"])})
        else:
            raise GrammarStdlibT30Error("catalog field domain is outside the structural contract")
    return _structural_first_use(result)


def _f4_review_target(task: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    result = envelope["result"]
    coverage = _coverage_for_task(task, result["ast"]["inventory"])
    mode = str(task["oracle"]["mode"])
    requested = None if mode == "source" else str(task["oracle"]["target"])
    endpoint: dict[str, Any] = {
        "count": result["endpoint"]["count"],
        "requested": requested,
        "selected": result["endpoint"]["name"],
    }
    variants = [
        str(node["name"])
        for node in _ast_nodes(result["ast"]["inventory"])
        if node.get("$type") == "VariantDecl" and isinstance(node.get("name"), str)
    ]
    if STRUCTURAL_FIRST_USE_DEDUP:
        variants = _unique(iter(variants))
    if F4_ENDPOINT_SHAPE == "explicit_mode_variants":
        endpoint = {
            "count": result["endpoint"]["count"],
            "mode": mode,
            "requested": requested,
            "selected": None if mode == "source" else result["endpoint"]["name"],
            "variants": variants,
        }
    elif F4_ENDPOINT_SHAPE == "legacy_optional_variant":
        if len(variants) > 1:
            raise GrammarStdlibT30Error("F4 review target has ambiguous variants")
        if variants:
            endpoint["variant"] = variants[0]
    else:
        raise GrammarStdlibT30Error("F4 endpoint contract configuration drift")
    return {
        "contract": F4_REVIEW_CONTRACT,
        "status": result["status"],
        **{field: coverage[field] for field in MODEL_JSON_COVERAGE_FIELDS},
        "endpoint": endpoint,
    }


def _f6_review_target(task: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    inventory = envelope["result"]["ast"]["inventory"]
    coverage = _coverage_for_task(task, inventory)
    result: dict[str, Any] = {
        "contract": F6_REVIEW_CONTRACT,
        "top_levels": coverage["top_levels"],
        "declarations": _declarations_from_inventory(inventory),
    }
    if F6_ALWAYS_CATALOG_FIELDS or "catalog_fields" in task["expected_json"]:
        result["catalog_fields"] = _catalog_fields(inventory)
    for field in MODEL_JSON_COVERAGE_FIELDS:
        if field != "top_levels":
            result[field] = coverage[field]
    result["relationships"] = _relationships_from_inventory(inventory)
    return result


def _task_content_root(task: Mapping[str, Any]) -> str:
    return canonical_hash(
        {
            key: task[key]
            for key in (
                "family",
                "kind",
                "task_mode",
                "prompt",
                "oracle",
                "input_source",
                "before_source",
                "expected_source",
                "expected_repaired_source",
                "expected_json",
            )
            if key in task
        }
    )


def _predecessor_terminal_diagnosis() -> dict[str, Any] | None:
    contract = PREDECESSOR_TERMINAL_EVALUATION
    if contract is None:
        return None
    if set(contract) != {
        "path",
        "relative_path",
        "evidence_id",
        "evaluation_sha256",
        "verdict",
        "disposition",
    }:
        raise GrammarStdlibT30Error("predecessor terminal-evaluation configuration drift")
    path = contract["path"]
    relative_path = contract["relative_path"]
    if (
        not isinstance(path, Path)
        or not isinstance(relative_path, str)
        or not relative_path
        or Path(relative_path).is_absolute()
        or ".." in Path(relative_path).parts
    ):
        raise GrammarStdlibT30Error("predecessor evaluation path is invalid")
    value, raw = _load(path, "predecessor T30 evaluation")
    _self_hash(value, "evaluation_sha256")
    decision = value.get("decision")
    if (
        value.get("evidence_id") != contract["evidence_id"]
        or value.get("evaluation_sha256") != contract["evaluation_sha256"]
        or value.get("status") != "verified_local_cooperative"
        or not isinstance(decision, Mapping)
        or decision.get("verdict") != contract["verdict"]
        or value.get("model_outputs_observed") is not True
        or value.get("training_authorized") is not False
        or value.get("delta_qlora_authorized") is not False
        or contract["disposition"] != "terminal_diagnosis_no_promotion"
    ):
        raise GrammarStdlibT30Error("predecessor evaluation is not terminal diagnosis")
    return {
        "path": relative_path,
        "bytes": len(raw),
        "file_sha256": raw_hash(raw),
        "evaluation_sha256": value["evaluation_sha256"],
        "verdict": decision["verdict"],
        "disposition": contract["disposition"],
    }


def build_truth(metis_root: Path, node_path: Path) -> dict[str, Any]:
    _manifest, tasks, task_raw = load_tasks()
    _reference, reference_raw = _reference_context()
    policy, _policy_raw = _policy()
    records: list[dict[str, Any]] = []
    with oracle.grammar_stdlib_oracle_session(
        metis_root=metis_root, node_path=node_path
    ) as session:
        pin = dict(session.pin_identity)
        for task in tasks:
            warning_only_timezone_repair = (
                "timezone-setting-invalid-key" in _declared_interaction_classes(task)
            )
            content_root = _task_content_root(task)
            target: dict[str, Any] = {
                "kind": task["task_mode"],
                "authority_tier": task["authority_tier"],
                "messages_sha256": canonical_hash(build_messages(task)),
                "declared_coverage": task["coverage"],
                "content_root_sha256": content_root,
                "before": None,
                "input": None,
                "repaired": None,
            }
            if task.get("before_source") is not None:
                target["before"], _before_envelope = _validate_source_envelope(
                    task,
                    str(task["before_source"]),
                    metis_root,
                    node_path,
                    session,
                    expected_ok=task["oracle"]["input_failure_kind"] is None,
                    expected_diagnostic_markers=(
                        tuple(task["oracle"]["diagnostic_substrings"])
                        if warning_only_timezone_repair
                        else ()
                    ),
                )
            input_envelope: dict[str, Any] | None = None
            if task.get("input_source") is not None:
                target["input"], input_envelope = _validate_source_envelope(
                    task,
                    str(task["input_source"]),
                    metis_root,
                    node_path,
                    session,
                    expected_ok=True,
                )
            if task.get("expected_repaired_source") is not None:
                target["repaired"], _repaired_envelope = _validate_source_envelope(
                    task,
                    str(task["expected_repaired_source"]),
                    metis_root,
                    node_path,
                    session,
                    expected_ok=True,
                    require_no_diagnostics=warning_only_timezone_repair,
                )
            if task["task_mode"] == "source_output":
                target["expected"], expected_envelope = _validate_source_envelope(
                    task,
                    str(task.get("expected_source", task.get("expected_repaired_source"))),
                    metis_root,
                    node_path,
                    session,
                    expected_ok=True,
                    require_no_diagnostics=warning_only_timezone_repair,
                )
                target["expected_coverage"] = _coverage_for_task(
                    task, expected_envelope["result"]["ast"]["inventory"]
                )
            else:
                if input_envelope is None:
                    raise GrammarStdlibT30Error("review task has no pinned input envelope")
                derived = (
                    _f4_review_target(task, input_envelope)
                    if task["family"] == "F-4"
                    else _f6_review_target(task, input_envelope)
                )
                if task["expected_json"] != derived:
                    raise GrammarStdlibT30Error(
                        f"review target is not derived from pinned AST: {task['task_id']}"
                    )
                target["expected_json_sha256"] = canonical_hash(derived)
                target["expected_coverage"] = _coverage_for_task(
                    task, input_envelope["result"]["ast"]["inventory"]
                )
            if target["expected_coverage"] != task["coverage"]:
                raise GrammarStdlibT30Error(
                    f"declared coverage differs from pinned AST: {task['task_id']}"
                )
            records.append(
                {
                    "task_id": task["task_id"],
                    "family": task["family"],
                    "authority_tier": task["authority_tier"],
                    "target": target,
                    "model_output_observed": False,
                }
            )
    body: dict[str, Any] = {
        "schema_version": 1,
        "truth_id": TRUTH_ID,
        "status": "truth_fixed_before_model_output",
        "authority_tier": "automatic",
        "benchmark_id": BENCHMARK_ID,
        "semantic_signature_contract": d18.SEMANTIC_SIGNATURE_CONTRACT,
        "tasks_file_sha256": raw_hash(task_raw),
        "reference_context_sha256": raw_hash(reference_raw),
        "policy_sha256": policy["policy_sha256"],
        "grammar_stdlib_pin": pin,
        "generation": GENERATION,
        "thresholds": THRESHOLDS,
        "counts": {
            "tasks_in": TASK_COUNT,
            "tasks_out": TASK_COUNT,
            "tasks_distinct": TASK_COUNT,
            "gaps": 0,
            "families": {family: TASKS_PER_FAMILY for family in FAMILIES},
        },
        "tasks": records,
        "model_outputs_observed": False,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "nonclaims": NONCLAIMS,
    }
    predecessor = _predecessor_terminal_diagnosis()
    if predecessor is not None:
        body["predecessor_terminal_diagnosis"] = predecessor
    _assert_disjoint(tasks, body)
    body["truth_sha256"] = canonical_hash(body)
    return body


def truth(args: argparse.Namespace) -> int:
    if TRUTH_PATH.exists() or TRUTH_PATH.is_symlink():
        raise GrammarStdlibT30Error("truth output already exists")
    body = build_truth(Path(args.metis_root), Path(args.node_path))
    _write_manifest_once(TRUTH_PATH, body)
    print(
        json.dumps(
            {"event": "grammar_stdlib_t30_truth", "truth_sha256": body["truth_sha256"]},
            sort_keys=True,
        )
    )
    return 0


def _pinned_git(repository: Path | None, *args: str, text: bool = True) -> str | bytes:
    try:
        return catalog_pin._run_git(repository, *args, text=text)
    except catalog_pin.CatalogMaintenancePinError as error:
        raise GrammarStdlibT30Error(f"pinned Git verification failed: {error}") from error


def _tracked_record(relative: str) -> dict[str, Any]:
    raw = _pinned_git(PROJECT_ROOT, "show", f"HEAD:{relative}", text=False)
    row = str(_pinned_git(PROJECT_ROOT, "ls-tree", "HEAD", "--", relative)).split()
    current = safe._read_regular(PROJECT_ROOT / relative, f"bound input {relative}")
    if not isinstance(raw, bytes) or len(row) != 4 or row[1] != "blob" or row[3] != relative:
        raise GrammarStdlibT30Error("bound input is not one pinned blob")
    record = {"path": relative, "bytes": len(raw), "sha256": raw_hash(raw), "git_blob_oid": row[2]}
    if raw_hash(current) != record["sha256"] or len(current) != record["bytes"]:
        raise GrammarStdlibT30Error(f"bound input differs from HEAD: {relative}")
    return record


def _published(remote: str) -> tuple[str, str, str]:
    if str(_pinned_git(PROJECT_ROOT, "status", "--porcelain", "--untracked-files=all")):
        raise GrammarStdlibT30Error("clean worktree is required")
    head = str(_pinned_git(PROJECT_ROOT, "rev-parse", "HEAD"))
    remote_ref = "refs/heads/" + str(_pinned_git(PROJECT_ROOT, "branch", "--show-current"))
    rows = str(_pinned_git(PROJECT_ROOT, "ls-remote", remote, remote_ref)).splitlines()
    if len(rows) != 1 or rows[0].split() != [head, remote_ref]:
        raise GrammarStdlibT30Error("current HEAD is not exactly published")
    return head, str(_pinned_git(PROJECT_ROOT, "rev-parse", "HEAD^{tree}")), remote_ref


def _historical_document(
    path: Path, label: str, self_hash_field: str
) -> tuple[dict[str, Any], bytes]:
    """Reopen one historical JSON receipt without replaying it against live sources."""

    try:
        raw = safe._read_regular(path, label, 16 * 1024 * 1024)
    except safe.DemoAccuracyError as error:
        raise GrammarStdlibT30Error(f"cannot reopen {label}") from error
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
        canonical = (json.dumps(value, allow_nan=False, sort_keys=True) + "\n").encode()
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise GrammarStdlibT30Error(f"{label} is not strict JSON") from error
    if not isinstance(value, dict) or raw != canonical:
        raise GrammarStdlibT30Error(f"{label} is not one canonical historical document")
    _self_hash(value, self_hash_field)
    return value, raw


def _historical_bound_input_roster(source: bytes) -> tuple[str, ...]:
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError) as error:
        raise GrammarStdlibT30Error("historical trainer source is not parseable") from error
    matches: list[Any] = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
            isinstance(target, ast.Name) and target.id == "BOUND_INPUTS"
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        ):
            try:
                matches.append(ast.literal_eval(node.value))
            except (TypeError, ValueError) as error:
                raise GrammarStdlibT30Error(
                    "historical trainer BOUND_INPUTS is not literal"
                ) from error
    if (
        len(matches) != 1
        or not isinstance(matches[0], tuple)
        or not matches[0]
        or any(not isinstance(item, str) or not item for item in matches[0])
        or len(set(matches[0])) != len(matches[0])
    ):
        raise GrammarStdlibT30Error("historical trainer BOUND_INPUTS roster drift")
    return matches[0]


def _verify_historical_training_freeze(
    value: Mapping[str, Any],
    *,
    dataset: Mapping[str, Any],
    runtime: Mapping[str, Any],
    base_checkpoint: Mapping[str, Any],
) -> int:
    """Verify old source bytes at their Git preimage, never against today's tree."""

    bound = value.get("bound_inputs")
    preimage = value.get("preimage_commit")
    baseline_origin = value.get("baseline_origin")
    expected_checkpoint = dict(base_checkpoint)
    if (
        value.get("schema_version") != 2
        or value.get("status") != "refrozen_after_base_before_training"
        or value.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or value.get("preimage_published") is not True
        or value.get("remote_head_at_freeze") != preimage
        or value.get("model_outputs_observed") is not True
        or value.get("training_started") is not False
        or value.get("model_replay_allowed") is not False
        or value.get("network") != "denied_during_model_and_optimizer_execution"
        or value.get("config") != trainer.CONFIG
        or value.get("limits") != trainer.LIMITS
        or value.get("runtime") != runtime
        or value.get("dataset_receipt_sha256") != dataset.get("receipt_sha256")
        or not isinstance(baseline_origin, Mapping)
        or value.get("checkpoint") != expected_checkpoint
        or value.get("checkpoint_report_sha256")
        != expected_checkpoint.get("verification_report_sha256")
        or not isinstance(preimage, str)
        or not isinstance(bound, Mapping)
    ):
        raise GrammarStdlibT30Error("historical training freeze contract drift")
    if str(_pinned_git(PROJECT_ROOT, "rev-parse", f"{preimage}^{{tree}}")) != value.get(
        "preimage_tree"
    ):
        raise GrammarStdlibT30Error("historical training freeze tree drift")
    _pinned_git(PROJECT_ROOT, "merge-base", "--is-ancestor", preimage, "HEAD")
    trainer_relative = "src/metis_model1/initial_local_qlora_train.py"
    trainer_source = _pinned_git(PROJECT_ROOT, "show", f"{preimage}:{trainer_relative}", text=False)
    if not isinstance(trainer_source, bytes):
        raise GrammarStdlibT30Error("historical trainer source is unavailable")
    roster = _historical_bound_input_roster(trainer_source)
    if set(bound) != set(roster):
        raise GrammarStdlibT30Error("historical training bound-input roster drift")
    for relative in roster:
        historical = _pinned_git(PROJECT_ROOT, "show", f"{preimage}:{relative}", text=False)
        if not isinstance(historical, bytes) or raw_hash(historical) != bound[relative]:
            raise GrammarStdlibT30Error(
                f"historical training bound input differs at preimage: {relative}"
            )
    return len(roster)


def _verify_historical_phase_chain(training: Mapping[str, Any], freeze: Mapping[str, Any]) -> None:
    evidence = training.get("evidence")
    phases = evidence.get("phases") if isinstance(evidence, Mapping) else None
    if (
        not isinstance(phases, list)
        or any(not isinstance(row, Mapping) for row in phases)
        or [row.get("step") for row in phases] != [25, 50]
    ):
        raise GrammarStdlibT30Error("historical training phase roster drift")
    for row in phases:
        step = int(row["step"])
        marker_path = trainer.RUN_ROOT / f"phase-step{step}-started.json"
        receipt_path = trainer.RUN_ROOT / f"phase-step{step}-receipt.json"
        marker, marker_raw = _historical_document(
            marker_path, f"historical step{step} marker", "marker_sha256"
        )
        receipt, receipt_raw = _historical_document(
            receipt_path, f"historical step{step} receipt", "receipt_sha256"
        )
        retained = receipt.get("retained_checkpoints")
        if not isinstance(retained, list) or any(
            not isinstance(item, Mapping) for item in retained
        ):
            raise GrammarStdlibT30Error(f"historical training step{step} receipt shape drift")
        if (
            raw_hash(marker_raw) != row.get("marker_sha256")
            or marker.get("marker_sha256") != row.get("marker_self_sha256")
            or raw_hash(receipt_raw) != row.get("phase_receipt_sha256")
            or receipt.get("receipt_sha256") != row.get("phase_receipt_self_sha256")
            or marker.get("target_step") != step
            or receipt.get("target_step") != step
            or marker.get("freeze_sha256") != freeze.get("freeze_sha256")
            or receipt.get("freeze_sha256") != freeze.get("freeze_sha256")
            or marker.get("continuation_authority_sha256")
            != row.get("continuation_authority_sha256")
            or receipt.get("continuation_authority_sha256")
            != row.get("continuation_authority_sha256")
            or receipt.get("telemetry_summary_sha256") != row.get("telemetry_summary_sha256")
            or [
                {
                    "global_step": item.get("global_step"),
                    "manifest_sha256": item.get("manifest_sha256"),
                    "checkpoint_sha256": item.get("checkpoint_sha256"),
                }
                for item in retained
            ]
            != row.get("retained_checkpoints")
        ):
            raise GrammarStdlibT30Error(f"historical training step{step} lineage drift")


def _opened_regular(path: Path) -> tuple[int, os.stat_result]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(nofollow, int):
        raise GrammarStdlibT30Error("O_NOFOLLOW is required for package verification")
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | nofollow)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise GrammarStdlibT30Error(f"package/live member is unsafe: {path}")
        return descriptor, metadata
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise GrammarStdlibT30Error(f"cannot safely open package/live member: {path}") from error


def _stable_open_identity(path: Path, descriptor: int, before: os.stat_result) -> None:
    try:
        after = os.fstat(descriptor)
        named = path.lstat()
    except OSError as error:
        raise GrammarStdlibT30Error(f"package/live member changed while reading: {path}") from error
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (
        any(getattr(before, field) != getattr(after, field) for field in fields)
        or stat.S_ISLNK(named.st_mode)
        or not stat.S_ISREG(named.st_mode)
        or named.st_nlink != 1
        or any(getattr(before, field) != getattr(named, field) for field in fields)
    ):
        raise GrammarStdlibT30Error(f"package/live member changed while reading: {path}")


def _regular_files_equal(left: Path, right: Path) -> bool:
    descriptors: list[int] = []
    try:
        left_fd, left_before = _opened_regular(left)
        descriptors.append(left_fd)
        right_fd, right_before = _opened_regular(right)
        descriptors.append(right_fd)
        equal = left_before.st_size == right_before.st_size
        while equal:
            left_chunk = os.read(left_fd, 8 * 1024 * 1024)
            right_chunk = os.read(right_fd, 8 * 1024 * 1024)
            if left_chunk != right_chunk:
                equal = False
                break
            if not left_chunk:
                break
        _stable_open_identity(left, left_fd, left_before)
        _stable_open_identity(right, right_fd, right_before)
        return equal
    except OSError as error:
        raise GrammarStdlibT30Error("cannot compare package and live member") from error
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def _streaming_hash(path: Path) -> tuple[int, str]:
    descriptor = -1
    try:
        descriptor, metadata = _opened_regular(path)
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 8 * 1024 * 1024):
            digest.update(chunk)
        _stable_open_identity(path, descriptor, metadata)
        return metadata.st_size, "sha256:" + digest.hexdigest()
    except OSError as error:
        raise GrammarStdlibT30Error("cannot hash package archive") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _verified_backup_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        verified = backup.verify_historical_receipt(require_published_remote=False)
    except (backup.BackupContractError, OSError) as error:
        raise GrammarStdlibT30Error("complete S3 backup receipt verification failed") from error
    if verified != value:
        raise GrammarStdlibT30Error("S3 backup receipt differs from complete verification")
    return verified


def _verify_package_backup_anchor() -> dict[str, Any]:
    package = qlora.verify_package(PACKAGE_DIR)
    for package_name, live_path in PACKAGE_LIVE_MEMBERS.items():
        if not _regular_files_equal(PACKAGE_DIR / package_name, live_path):
            raise GrammarStdlibT30Error(f"package member differs from live payload: {package_name}")

    preimage, preimage_raw = _historical_document(
        BACKUP_PREIMAGE_PATH, "backup preimage", "preimage_sha256"
    )
    archive_receipt, archive_receipt_raw = _historical_document(
        ARCHIVE_RECEIPT_PATH, "archive receipt", "receipt_sha256"
    )
    backup_receipt, backup_receipt_raw = _historical_document(
        BACKUP_RECEIPT_PATH, "remote backup receipt", "receipt_sha256"
    )
    _verified_backup_receipt(backup_receipt)
    archive_bytes, archive_sha256 = _streaming_hash(ARCHIVE_PATH)
    archive = {
        "bytes": archive_bytes,
        "path": str(ARCHIVE_PATH.relative_to(PROJECT_ROOT)),
        "sha256": archive_sha256,
    }
    publication_head = backup_receipt.get("publication_head")
    preimage_fresh = preimage.get("fresh_restore")
    archive_fresh = archive_receipt.get("fresh_restore")
    archive_payload = archive_receipt.get("archive")
    backup_download = backup_receipt.get("download")
    backup_fresh = backup_receipt.get("fresh_restore")
    backup_head = backup_receipt.get("head")
    if any(
        not isinstance(item, Mapping)
        for item in (
            preimage_fresh,
            archive_fresh,
            archive_payload,
            backup_download,
            backup_fresh,
            backup_head,
        )
    ):
        raise GrammarStdlibT30Error("backup/package nested receipt shape drift")
    if (
        preimage.get("schema_version") != 1
        or preimage.get("preimage_id") != "initial-local-qlora-s3-backup-preimage/v1"
        or preimage.get("status") != "prepared_before_s3_transfer"
        or preimage.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or preimage.get("package_sha256") != package.get("package_sha256")
        or preimage.get("archive") != archive
        or preimage.get("archive_receipt")
        != {
            "path": str(ARCHIVE_RECEIPT_PATH.relative_to(PROJECT_ROOT)),
            "bytes": len(archive_receipt_raw),
            "sha256": raw_hash(archive_receipt_raw),
            "self_sha256": archive_receipt.get("receipt_sha256"),
        }
        or preimage_fresh
        != {
            "global_step": package.get("global_step"),
            "member_count": package.get("files"),
            "package_files": package.get("files"),
            "package_sha256": package.get("package_sha256"),
            "package_status": package.get("status"),
            "status": "fresh_restore_verified",
            "verdict": package.get("verdict"),
        }
        or archive_fresh.get("status") != "fresh_restore_verified"
        or archive_fresh.get("package") != package
    ):
        raise GrammarStdlibT30Error("tracked backup preimage/package anchor drift")
    preimage_commit = preimage.get("preimage_commit")
    if (
        not isinstance(preimage_commit, str)
        or str(_pinned_git(PROJECT_ROOT, "rev-parse", f"{preimage_commit}^{{tree}}"))
        != preimage.get("preimage_tree")
        or not isinstance(publication_head, str)
    ):
        raise GrammarStdlibT30Error("backup publication Git identity drift")
    _pinned_git(PROJECT_ROOT, "merge-base", "--is-ancestor", preimage_commit, publication_head)
    _pinned_git(PROJECT_ROOT, "merge-base", "--is-ancestor", publication_head, "HEAD")
    published_preimage = _pinned_git(
        PROJECT_ROOT,
        "show",
        f"{publication_head}:{BACKUP_PREIMAGE_PATH.relative_to(PROJECT_ROOT)}",
        text=False,
    )
    if published_preimage != preimage_raw:
        raise GrammarStdlibT30Error("backup preimage differs at publication head")
    if (
        archive_receipt.get("schema_version") != 1
        or archive_receipt.get("status") != "sealed"
        or archive_receipt.get("package_sha256") != package.get("package_sha256")
        or archive_payload.get("bytes") != archive_bytes
        or archive_payload.get("sha256") != archive_sha256
        or backup_receipt.get("schema_version") != 1
        or backup_receipt.get("status") != "uploaded_versioned_restore_verified"
        or backup_receipt.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or backup_receipt.get("preimage_file_sha256") != raw_hash(preimage_raw)
        or backup_receipt.get("preimage_self_sha256") != preimage.get("preimage_sha256")
        or backup_receipt.get("package_sha256") != package.get("package_sha256")
        or backup_receipt.get("archive") != {"bytes": archive_bytes, "sha256": archive_sha256}
        or backup_download.get("bytes") != archive_bytes
        or backup_download.get("sha256") != archive_sha256
        or not isinstance(backup_download.get("version_id"), str)
        or not backup_download["version_id"]
        or backup_fresh != preimage_fresh
        or backup_receipt.get("put_attempts") != 1
        or backup_receipt.get("raw_process_output_retained") is not False
        or backup_head.get("current_version_matches") is not True
    ):
        raise GrammarStdlibT30Error("remote backup receipt/package anchor drift")
    return {
        "package_sha256": package["package_sha256"],
        "package_files": package["files"],
        "archive_bytes": archive_bytes,
        "archive_sha256": archive_sha256,
        "archive_receipt_sha256": raw_hash(archive_receipt_raw),
        "archive_receipt_self_sha256": archive_receipt["receipt_sha256"],
        "backup_preimage_sha256": raw_hash(preimage_raw),
        "backup_preimage_self_sha256": preimage["preimage_sha256"],
        "backup_receipt_sha256": raw_hash(backup_receipt_raw),
        "backup_receipt_self_sha256": backup_receipt["receipt_sha256"],
        "backup_publication_head": publication_head,
        "remote_version_id": backup_download["version_id"],
        "live_package_members_exact": True,
    }


def _replay_historical_dev_bundles() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Replay every distinct historical dev source in one pinned Oracle snapshot."""

    with qlora._dev_oracle_replay(
        qlora.DEFAULT_PINNED_METIS_ROOT, qlora.DEFAULT_NODE_PATH
    ) as oracle_replay:
        base_bundle = qlora._verified_dev_bundle(
            "base",
            dataset_receipt=DATASET_RECEIPT_PATH,
            adapter=None,
            oracle_replay=oracle_replay,
        )
        gate_bundles = [
            qlora._verified_dev_bundle(
                f"step{step}",
                dataset_receipt=DATASET_RECEIPT_PATH,
                adapter=trainer.CHECKPOINT_ROOT / f"step-{step:08d}",
                oracle_replay=oracle_replay,
            )
            for step in (25, 50)
        ]
        restored_bundle = qlora._verified_dev_bundle(
            "restored",
            dataset_receipt=DATASET_RECEIPT_PATH,
            adapter=None,
            oracle_replay=oracle_replay,
        )
    return base_bundle, gate_bundles, restored_bundle


def _verify_historical_adapter_chain(
    *,
    dataset: Mapping[str, Any],
    runtime: Mapping[str, Any],
    base_identity: Mapping[str, Any],
    base_checkpoint: Mapping[str, Any],
    adapter_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Replay payload/dev evidence while checking old source evidence at its old commit."""

    freeze, freeze_raw = _historical_document(
        trainer.FREEZE_PATH, "historical training freeze", "freeze_sha256"
    )
    historical_bound_inputs = _verify_historical_training_freeze(
        freeze,
        dataset=dataset,
        runtime=runtime,
        base_checkpoint=base_checkpoint,
    )
    training, training_raw = _historical_document(
        qlora.DEFAULT_TRAINING_RECEIPT,
        "historical training receipt",
        "training_sha256",
    )
    reuse, reuse_raw = _historical_document(
        trainer.REUSE_RECEIPT_PATH,
        "historical baseline reuse receipt",
        "receipt_sha256",
    )
    evidence = training.get("evidence")
    adapter = adapter_identity.get("adapter")
    baseline_origin = freeze.get("baseline_origin")
    if not isinstance(baseline_origin, Mapping):
        raise GrammarStdlibT30Error("historical baseline origin shape drift")
    try:
        adapter_config_sha256 = raw_hash(
            safe._read_regular(ADAPTER_PATH / "adapter_config.json", "adapter config")
        )
    except safe.DemoAccuracyError as error:
        raise GrammarStdlibT30Error("cannot reopen historical adapter config") from error
    if (
        training.get("schema_version") != 1
        or training.get("status") != "verified"
        or training.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or training.get("mode") != "single_config_no_retry_qlora"
        or training.get("dataset_receipt_sha256") != dataset.get("receipt_sha256")
        or not isinstance(evidence, Mapping)
        or not isinstance(adapter, Mapping)
        or evidence.get("freeze_file_sha256") != raw_hash(freeze_raw)
        or evidence.get("freeze_self_sha256") != freeze.get("freeze_sha256")
        or evidence.get("baseline_reuse_receipt_file_sha256") != raw_hash(reuse_raw)
        or evidence.get("baseline_reuse_receipt_self_sha256") != reuse.get("receipt_sha256")
        or evidence.get("baseline_origin_sha256") != canonical_hash(baseline_origin)
        or evidence.get("preimage_commit") != freeze.get("preimage_commit")
        or evidence.get("checkpoint")
        != {
            "global_step": adapter.get("global_step"),
            "model_revision": base_identity.get("base_revision"),
            "manifest_sha256": adapter.get("manifest_sha256"),
            "adapter_sha256": adapter.get("adapter_sha256"),
            "adapter_config_sha256": adapter_config_sha256,
        }
    ):
        raise GrammarStdlibT30Error("historical training receipt lineage drift")
    execution_head = evidence.get("published_execution_head")
    if not isinstance(execution_head, str):
        raise GrammarStdlibT30Error("historical training execution head is invalid")
    _pinned_git(
        PROJECT_ROOT,
        "merge-base",
        "--is-ancestor",
        str(freeze["preimage_commit"]),
        execution_head,
    )
    _pinned_git(PROJECT_ROOT, "merge-base", "--is-ancestor", execution_head, "HEAD")
    published_freeze = _pinned_git(
        PROJECT_ROOT,
        "show",
        f"{execution_head}:{trainer.FREEZE_PATH.relative_to(PROJECT_ROOT)}",
        text=False,
    )
    if published_freeze != freeze_raw:
        raise GrammarStdlibT30Error("historical training freeze differs at execution head")
    _verify_historical_phase_chain(training, freeze)

    selection, selection_raw = _historical_document(
        qlora.DEFAULT_SELECTION_RECEIPT,
        "historical selection receipt",
        "selection_sha256",
    )
    base_bundle, gate_bundles, restored_bundle = _replay_historical_dev_bundles()
    if (
        selection.get("schema_version") != 1
        or selection.get("status") != "selected"
        or selection.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or selection.get("selection_surface") != "frozen_dev16_only"
        or selection.get("b12_observed") is not False
        or selection.get("selected_step") != adapter.get("global_step")
        or selection.get("checkpoint_manifest_sha256") != adapter.get("manifest_sha256")
        or selection.get("adapter_sha256") != adapter.get("adapter_sha256")
        or selection.get("model_revision") != base_identity.get("base_revision")
        or selection.get("dataset_receipt_sha256") != dataset.get("receipt_sha256")
        or selection.get("training_receipt_sha256") != raw_hash(training_raw)
        or selection.get("training_self_sha256") != training.get("training_sha256")
        or selection.get("base_evidence") != base_bundle
        or selection.get("gate_evidence") != gate_bundles
        or selection.get("base_semantic_correct") != base_bundle["score"]
        or selection.get("selected_semantic_correct") != gate_bundles[-1]["score"]
        or selection.get("evidence_roster_sha256")
        != canonical_hash({"base": base_bundle, "gates": gate_bundles})
    ):
        raise GrammarStdlibT30Error("historical selection receipt lineage drift")

    restore, restore_raw = _historical_document(
        qlora.DEFAULT_RESTORE_RECEIPT,
        "historical adapter-off restore receipt",
        "restore_sha256",
    )
    candidate_match = dict(base_bundle["files"]["candidates"])
    candidate_match["path"] = restored_bundle["files"]["candidates"]["path"]
    if (
        restore.get("schema_version") != 1
        or restore.get("status") != "verified"
        or restore.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or restore.get("mode") != "adapter_off_exact_restore"
        or restore.get("dataset_receipt_sha256") != dataset.get("receipt_sha256")
        or restore.get("selection_receipt_sha256") != raw_hash(selection_raw)
        or restore.get("selection_self_sha256") != selection.get("selection_sha256")
        or restore.get("selected_step") != selection.get("selected_step")
        or restore.get("adapter_sha256") != adapter.get("adapter_sha256")
        or restore.get("initial_base_evidence") != base_bundle
        or restore.get("restored_base_evidence") != restored_bundle
        or restore.get("exact_candidate_restore") is not True
        or restored_bundle["files"]["candidates"] != candidate_match
    ):
        raise GrammarStdlibT30Error("historical adapter-off restore lineage drift")
    return {
        "verification": "historical_preimage_plus_live_payload_and_dev_replay",
        "path": str(qlora.DEFAULT_RESTORE_RECEIPT.relative_to(PROJECT_ROOT)),
        "bytes": len(restore_raw),
        "sha256": raw_hash(restore_raw),
        "restore_sha256": restore["restore_sha256"],
        "selection_receipt_sha256": raw_hash(selection_raw),
        "selection_self_sha256": selection["selection_sha256"],
        "training_receipt_sha256": raw_hash(training_raw),
        "training_self_sha256": training["training_sha256"],
        "training_freeze_sha256": raw_hash(freeze_raw),
        "training_freeze_self_sha256": freeze["freeze_sha256"],
        "training_preimage_commit": freeze["preimage_commit"],
        "historical_bound_inputs": historical_bound_inputs,
        "historical_git_replay": True,
        "selected_step": restore["selected_step"],
        "adapter_sha256": restore["adapter_sha256"],
        "initial_candidate_sha256": base_bundle["files"]["candidates"]["sha256"],
        "restored_candidate_sha256": restored_bundle["files"]["candidates"]["sha256"],
        "exact_candidate_restore": True,
    }


def _runtime_identities() -> dict[str, Any]:
    dataset = qlora._check_receipt(DATASET_RECEIPT_PATH)
    runtime = qlora._check_runtime()
    base_checkpoint = qlora._check_checkpoint(qlora.BASE_CHECKPOINT)
    base = qlora.evaluation_identity(qlora.BASE_CHECKPOINT, None)
    adapter = qlora.evaluation_identity(qlora.BASE_CHECKPOINT, ADAPTER_PATH)
    package_backup = _verify_package_backup_anchor()
    return {
        "runtime": runtime,
        "base": base,
        "adapter": adapter,
        "dataset": dataset,
        "adapter_off_restore": _verify_historical_adapter_chain(
            dataset=dataset,
            runtime=runtime,
            base_identity=base,
            base_checkpoint=base_checkpoint,
            adapter_identity=adapter,
        ),
        "package_backup": package_backup,
        "worker_process_isolation": "base_and_adapter_run_in_separate_fresh_processes",
    }


def _run_dir() -> Path:
    return RUN_ROOT / RUN_ID


def _assert_ignored(relative: str) -> None:
    status = _pinned_git(PROJECT_ROOT, "check-ignore", "-q", relative)
    # catalog_pin returns empty stdout on success; non-zero is already rejected.
    if status not in {"", b""}:
        raise GrammarStdlibT30Error("T30 run directory is not ignored")


def _assert_disjoint(tasks: list[Mapping[str, Any]], truth: Mapping[str, Any]) -> None:
    """T30 must not reuse D18 identifiers, prompts/messages or semantic targets."""
    _d18_manifest, d18_tasks, _d18_raw = d18.load_tasks()
    d18_truth, _raw = d18._load(d18.TRUTH_PATH, "D18 truth")
    prior_tasks: list[Mapping[str, Any]] = list(d18_tasks)
    prior_truths: list[Mapping[str, Any]] = [d18_truth]
    for path in ADDITIONAL_FRESHNESS_TASK_PATHS:
        value, _extra_raw = _load(path, f"freshness tasks {path.name}")
        rows = value.get("tasks")
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise GrammarStdlibT30Error("freshness task roster is invalid")
        prior_tasks.extend(rows)
    for path in ADDITIONAL_FRESHNESS_TRUTH_PATHS:
        value, _extra_raw = _load(path, f"freshness truth {path.name}")
        _self_hash(value, "truth_sha256")
        rows = value.get("tasks")
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise GrammarStdlibT30Error("freshness truth roster is invalid")
        prior_truths.append(value)
    prior_ids = {str(row["task_id"]) for row in prior_tasks} | {
        str(row["task_id"]) for value in prior_truths for row in value["tasks"]
    }
    if prior_ids & {str(row["task_id"]) for row in tasks}:
        raise GrammarStdlibT30Error("T30 task identifiers overlap D18")
    d18_messages = {d18.canonical_hash(d18.build_messages(row)) for row in d18_tasks}
    prior_truth_messages = {
        str(target["messages_sha256"])
        for value in prior_truths[1:]
        for row in value["tasks"]
        if isinstance((target := row.get("target")), Mapping)
        and isinstance(target.get("messages_sha256"), str)
    }
    messages = {canonical_hash(build_messages(row)) for row in tasks}
    if (d18_messages | prior_truth_messages) & messages:
        raise GrammarStdlibT30Error("T30 messages overlap D18")
    content_roots = [_task_content_root(row) for row in tasks]
    declared_roots = [item["target"].get("content_root_sha256") for item in truth["tasks"]]
    if any(value is not None for value in declared_roots) and declared_roots != content_roots:
        raise GrammarStdlibT30Error("T30 truth content roots differ from its roster")
    if len(content_roots) != TASK_COUNT or len(set(content_roots)) != TASK_COUNT:
        raise GrammarStdlibT30Error("T30 content-derived roots are not distinct")
    if set(content_roots) & {_task_content_root(row) for row in prior_tasks}:
        raise GrammarStdlibT30Error("T30 content-derived root overlaps D18")

    def semantic_hashes(value: Mapping[str, Any]) -> set[str]:
        hashes: set[str] = set()
        for item in value["tasks"]:
            target = item["target"]
            for key in ("expected", "before", "input", "repaired"):
                if target.get(key) is not None:
                    hashes.add(canonical_hash(target[key]))
            if target.get("expected_json_sha256") is not None:
                hashes.add(str(target["expected_json_sha256"]))
        return hashes

    if semantic_hashes(truth) & {item for prior in prior_truths for item in semantic_hashes(prior)}:
        raise GrammarStdlibT30Error("T30 semantic targets overlap D18")
    tracked = str(_pinned_git(PROJECT_ROOT, "ls-files", "fixtures")).splitlines()
    historical = [
        path
        for path in tracked
        if path
        not in {
            str(TASKS_PATH.relative_to(PROJECT_ROOT)),
            str(REFERENCE_PATH.relative_to(PROJECT_ROOT)),
        }
    ]
    for path in historical:
        raw = _pinned_git(PROJECT_ROOT, "show", f"HEAD:{path}", text=False)
        if not isinstance(raw, bytes) or FRESHNESS_NAMESPACE in raw:
            raise GrammarStdlibT30Error("T30 namespace overlaps a historical fixture")
    qlora._check_receipt(DATASET_RECEIPT_PATH)
    for split in ("train.jsonl", "dev.jsonl"):
        raw = safe._read_regular(
            DATASET_RECEIPT_PATH.parent / split,
            f"verified training split {split}",
            64 * 1024 * 1024,
        )
        if FRESHNESS_NAMESPACE in raw:
            raise GrammarStdlibT30Error("T30 namespace overlaps frozen train/dev")


def build_freeze(remote: str, metis_root: Path, node_path: Path) -> dict[str, Any]:
    head, tree, remote_ref = _published(remote)
    run_dir = _run_dir()
    if run_dir.exists() or run_dir.is_symlink():
        raise GrammarStdlibT30Error("fixed T30 run directory already exists")
    _assert_ignored(RUN_RELATIVE)
    truth_value, _truth_raw = _load(TRUTH_PATH, "T30 truth")
    policy, policy_raw = _policy()
    _self_hash(truth_value, "truth_sha256")
    rebuilt = build_truth(metis_root, node_path)
    if truth_value != rebuilt:
        raise GrammarStdlibT30Error("truth differs from fresh pinned oracle reconstruction")
    _manifest, tasks, task_raw = load_tasks()
    _reference, reference_raw = _reference_context()
    _assert_disjoint(tasks, truth_value)
    body: dict[str, Any] = {
        "schema_version": 1,
        "freeze_id": FREEZE_ID,
        "status": "frozen_before_model_output",
        "authority_tier": "automatic",
        "preimage_commit": head,
        "preimage_tree": tree,
        "remote": remote,
        "remote_ref": remote_ref,
        "run_id": RUN_ID,
        "run_dir": RUN_RELATIVE,
        "attempt_nonce": ATTEMPT_NONCE,
        "bound_inputs": [_tracked_record(path) for path in BOUND_PATHS],
        "truth_sha256": truth_value["truth_sha256"],
        "policy_sha256": policy["policy_sha256"],
        "policy_file_sha256": raw_hash(policy_raw),
        "tasks_file_sha256": raw_hash(task_raw),
        "reference_context_sha256": raw_hash(reference_raw),
        "semantic_signature_contract": d18.SEMANTIC_SIGNATURE_CONTRACT,
        "runtime_identities": _runtime_identities(),
        "generation": GENERATION,
        "thresholds": THRESHOLDS,
        "model_outputs_observed": False,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "nonclaims": NONCLAIMS,
    }
    predecessor = _predecessor_terminal_diagnosis()
    if predecessor is not None:
        body["predecessor_terminal_diagnosis"] = predecessor
    body["freeze_sha256"] = canonical_hash(body)
    return body


def freeze(args: argparse.Namespace) -> int:
    if FREEZE_PATH.exists() or FREEZE_PATH.is_symlink():
        raise GrammarStdlibT30Error("freeze output already exists")
    body = build_freeze(args.remote, Path(args.metis_root), Path(args.node_path))
    _write_manifest_once(FREEZE_PATH, body)
    print(
        json.dumps(
            {"event": "grammar_stdlib_t30_freeze", "freeze_sha256": body["freeze_sha256"]},
            sort_keys=True,
        )
    )
    return 0


def _verify_bound(records: list[Mapping[str, Any]]) -> None:
    if [item.get("path") for item in records] != list(BOUND_PATHS):
        raise GrammarStdlibT30Error("T30 bound input roster drift")
    if any(_tracked_record(str(item["path"])) != item for item in records):
        raise GrammarStdlibT30Error("T30 bound input changed")


def _verify_freeze(value: Mapping[str, Any], head: str) -> Path:
    _self_hash(value, "freeze_sha256")
    required = {
        "schema_version",
        "freeze_id",
        "status",
        "authority_tier",
        "preimage_commit",
        "preimage_tree",
        "remote",
        "remote_ref",
        "run_id",
        "run_dir",
        "attempt_nonce",
        "bound_inputs",
        "truth_sha256",
        "policy_sha256",
        "policy_file_sha256",
        "tasks_file_sha256",
        "reference_context_sha256",
        "semantic_signature_contract",
        "runtime_identities",
        "generation",
        "thresholds",
        "model_outputs_observed",
        "training_authorized",
        "delta_qlora_authorized",
        "nonclaims",
        "freeze_sha256",
    }
    predecessor = _predecessor_terminal_diagnosis()
    if predecessor is not None:
        required.add("predecessor_terminal_diagnosis")
    if (
        set(value) != required
        or value.get("schema_version") != 1
        or value.get("freeze_id") != FREEZE_ID
        or value.get("status") != "frozen_before_model_output"
        or value.get("authority_tier") != "automatic"
        or value.get("run_id") != RUN_ID
        or value.get("run_dir") != RUN_RELATIVE
        or value.get("attempt_nonce") != ATTEMPT_NONCE
        or value.get("generation") != GENERATION
        or value.get("thresholds") != THRESHOLDS
        or value.get("semantic_signature_contract") != d18.SEMANTIC_SIGNATURE_CONTRACT
        or value.get("model_outputs_observed") is not False
        or value.get("training_authorized") is not False
        or value.get("delta_qlora_authorized") is not False
        or value.get("nonclaims") != NONCLAIMS
        or (predecessor is not None and value.get("predecessor_terminal_diagnosis") != predecessor)
    ):
        raise GrammarStdlibT30Error("freeze is not a T30 pre-output seal")
    if (
        str(_pinned_git(PROJECT_ROOT, "rev-parse", f"{value['preimage_commit']}^{{tree}}"))
        != value["preimage_tree"]
    ):
        raise GrammarStdlibT30Error("freeze preimage tree drift")
    _pinned_git(PROJECT_ROOT, "merge-base", "--is-ancestor", str(value["preimage_commit"]), head)
    _verify_bound(list(value["bound_inputs"]))
    return _run_dir()


def _verify_frozen_inputs(
    value: Mapping[str, Any], metis_root: Path, node_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _manifest, tasks, task_raw = load_tasks()
    _reference, reference_raw = _reference_context()
    policy, policy_raw = _policy()
    truth_value, _raw = _load(TRUTH_PATH, "T30 truth")
    _self_hash(truth_value, "truth_sha256")
    if (
        truth_value != build_truth(metis_root, node_path)
        or truth_value.get("truth_sha256") != value.get("truth_sha256")
        or truth_value.get("policy_sha256") != policy.get("policy_sha256")
        or value.get("policy_sha256") != policy.get("policy_sha256")
        or value.get("policy_file_sha256") != raw_hash(policy_raw)
        or raw_hash(task_raw) != value.get("tasks_file_sha256")
        or raw_hash(reference_raw) != value.get("reference_context_sha256")
        or _runtime_identities() != value.get("runtime_identities")
        or (
            (predecessor := _predecessor_terminal_diagnosis()) is not None
            and truth_value.get("predecessor_terminal_diagnosis") != predecessor
        )
    ):
        raise GrammarStdlibT30Error("frozen T30 inputs drifted")
    _assert_disjoint(tasks, truth_value)
    return tasks, truth_value


def _json_key_order_matches(value: Any, expected: Any) -> bool:
    if isinstance(expected, Mapping):
        return (
            isinstance(value, Mapping)
            and list(value) == list(expected)
            and all(_json_key_order_matches(value[key], expected[key]) for key in expected)
        )
    if isinstance(expected, list):
        return (
            isinstance(value, list)
            and len(value) == len(expected)
            and all(
                _json_key_order_matches(left, right)
                for left, right in zip(value, expected, strict=True)
            )
        )
    return True


_TOP_LEVEL_SURFACE_ALIASES = {
    "tenant": "Tenant",
    "catalog": "Catalog",
    "property": "Property",
    "endpoint": "Endpoint",
    "preset": "Preset",
    "list": "List",
    "transformer": "Transformer",
    "block": "NamedBlock",
    "settings": "SettingsDecl",
    "values": "ValueSet",
}


def _vocabulary_classification(field: str, items: list[str], allowed: set[str]) -> str | None:
    aliases: dict[str, str] = {}
    wrong_nature: set[str] = set()
    if field == "top_levels":
        aliases = _TOP_LEVEL_SURFACE_ALIASES
    elif field == "stdlib_members":
        aliases = {f"std.{item}": item for item in allowed if not item.startswith("time.")}
        wrong_nature = {f"std.{item}" for item in allowed if item.startswith("time.")}
    elif field == "stdlib_settings":
        aliases = {"timezone": "time.timezone", "settings.timezone": "time.timezone"}
    elif field == "stdlib_modules":
        aliases = {f"std.{item}": item for item in allowed}
    if len(items) != len(set(items)):
        return CONTRACT_MISMATCH_FAILURE_CODE
    mismatch = False
    for item in items:
        if item in allowed:
            continue
        if item in wrong_nature:
            return "stdlib_nature_mismatch"
        if aliases.get(item) in allowed:
            mismatch = True
            continue
        return "invented_symbol"
    return CONTRACT_MISMATCH_FAILURE_CODE if mismatch else None


def _known_task_symbol_strings(task: Mapping[str, Any]) -> set[str]:
    source = "\n".join(
        str(task[field])
        for field in ("input_source", "before_source")
        if isinstance(task.get(field), str)
    )
    identifiers = set(re.findall(r"@?[A-Za-z_][A-Za-z0-9_.]*", source))
    identifiers.update(item.removeprefix("@") for item in tuple(identifiers))
    identifiers.update(re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', source))
    return identifiers


def _same_items_out_of_order(value: list[Any], expected: Any) -> bool:
    if not isinstance(expected, list) or len(value) != len(expected):
        return False
    left = [canonical_hash(item) for item in value]
    right = [canonical_hash(item) for item in expected]
    return left != right and Counter(left) == Counter(right)


def _review_json_contract_failure_with_aliases(task: Mapping[str, Any], value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return CONTRACT_MISMATCH_FAILURE_CODE
    expected_json = task.get("expected_json")
    if not isinstance(expected_json, Mapping):
        raise GrammarStdlibT30Error("sealed review JSON is unavailable")
    alias_mismatch = list(value) != list(expected_json)
    alias_mismatch |= value.get("contract") != expected_json.get("contract")
    if task["family"] == "F-4":
        alias_mismatch |= value.get("status") != expected_json.get("status")
    coverage_domains = _coverage_domains()
    for key in MODEL_JSON_COVERAGE_FIELDS:
        items = value.get(key)
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            return CONTRACT_MISMATCH_FAILURE_CODE
        failure = _vocabulary_classification(key, items, coverage_domains[key])
        if failure not in {None, CONTRACT_MISMATCH_FAILURE_CODE}:
            return failure
        alias_mismatch |= failure == CONTRACT_MISMATCH_FAILURE_CODE
        alias_mismatch |= _same_items_out_of_order(items, expected_json.get(key))
    if task["family"] == "F-6":
        declarations = value.get("declarations")
        relationships = value.get("relationships")
        if not isinstance(declarations, list) or any(
            not isinstance(item, Mapping)
            or set(item) != {"kind", "name"}
            or not isinstance(item.get("kind"), str)
            or not isinstance(item.get("name"), str)
            or not item["name"]
            for item in declarations
        ):
            return CONTRACT_MISMATCH_FAILURE_CODE
        if len(declarations) != len({canonical_hash(item) for item in declarations}):
            return CONTRACT_MISMATCH_FAILURE_CODE
        alias_mismatch |= _same_items_out_of_order(declarations, expected_json.get("declarations"))
        expected_declarations = expected_json.get("declarations", [])
        expected_names = {
            item["name"] for item in expected_declarations if isinstance(item, Mapping)
        }
        expected_named_blocks = {
            item["name"]
            for item in expected_declarations
            if isinstance(item, Mapping) and item.get("kind") == "NamedBlock"
        }
        known_task_symbols = _known_task_symbol_strings(task)
        for item in declarations:
            kind = str(item["kind"])
            classification = _vocabulary_classification("top_levels", [kind], TOP_LEVELS)
            if classification == "invented_symbol":
                return classification
            alias_mismatch |= classification == CONTRACT_MISMATCH_FAILURE_CODE
            name = str(item["name"])
            if name not in expected_names:
                if (
                    name.startswith("block.")
                    and name.removeprefix("block.") in expected_named_blocks
                ) or name in known_task_symbols:
                    alias_mismatch = True
                else:
                    return "invented_symbol"
        if not isinstance(relationships, list) or any(
            not isinstance(item, str) for item in relationships
        ):
            return CONTRACT_MISMATCH_FAILURE_CODE
        if len(relationships) != len(set(relationships)):
            return CONTRACT_MISMATCH_FAILURE_CODE
        alias_mismatch |= _same_items_out_of_order(
            relationships, expected_json.get("relationships")
        )
        if not set(relationships).issubset(RELATIONSHIP_LABELS):
            alias_mismatch = True
        fields = value.get("catalog_fields")
        allowed_domains = {"implicit", "external-enum", "open"}
        if CATALOG_INLINE_DOMAIN_SUPPORTED:
            allowed_domains.add("inline")
        domain_aliases = {"none": "implicit", "enum": "external-enum", "values": "inline"}
        expected_fields = {
            item["name"]
            for item in expected_json.get("catalog_fields", [])
            if isinstance(item, Mapping)
        }
        if fields is not None:
            if not isinstance(fields, list) or any(
                not isinstance(item, Mapping) for item in fields
            ):
                return CONTRACT_MISMATCH_FAILURE_CODE
            if len(fields) != len({canonical_hash(item) for item in fields}):
                return CONTRACT_MISMATCH_FAILURE_CODE
            alias_mismatch |= _same_items_out_of_order(fields, expected_json.get("catalog_fields"))
            for item in fields:
                domain = item.get("domain")
                if not isinstance(domain, str):
                    return CONTRACT_MISMATCH_FAILURE_CODE
                if domain not in allowed_domains:
                    if (
                        domain_aliases.get(domain) in allowed_domains
                        or domain in known_task_symbols
                    ):
                        alias_mismatch = True
                    else:
                        return "invented_symbol"
                canonical_domain = domain_aliases.get(domain, domain)
                required_keys = (
                    {"name", "domain", "size"}
                    if canonical_domain in {"inline", "external-enum"}
                    else {"name", "domain"}
                )
                if set(item) != required_keys:
                    return CONTRACT_MISMATCH_FAILURE_CODE
                if canonical_domain in {"inline", "external-enum"} and (
                    not isinstance(item.get("size"), int)
                    or isinstance(item.get("size"), bool)
                    or item["size"] < 0
                ):
                    return CONTRACT_MISMATCH_FAILURE_CODE
                name = item.get("name")
                if not isinstance(name, str) or not name:
                    return CONTRACT_MISMATCH_FAILURE_CODE
                if name not in expected_fields:
                    if name in known_task_symbols:
                        alias_mismatch = True
                    else:
                        return "invented_symbol"
    if task["family"] == "F-4":
        endpoint = value.get("endpoint")
        expected_endpoint = expected_json["endpoint"]
        if not isinstance(endpoint, Mapping):
            return CONTRACT_MISMATCH_FAILURE_CODE
        alias_mismatch |= list(endpoint) != list(expected_endpoint)
        count = endpoint.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            return CONTRACT_MISMATCH_FAILURE_CODE
        known_names = {
            item
            for key in ("requested", "selected")
            if isinstance((item := expected_endpoint.get(key)), str)
        }
        known_names.update(_known_task_symbol_strings(task))
        for key in ("requested", "selected"):
            item = endpoint.get(key)
            if item is not None and not isinstance(item, str):
                return CONTRACT_MISMATCH_FAILURE_CODE
            if item is not None and item != expected_endpoint.get(key):
                if item in known_names:
                    alias_mismatch = True
                else:
                    return "invented_symbol"
        if F4_ENDPOINT_SHAPE == "explicit_mode_variants":
            mode = endpoint.get("mode")
            if mode not in {"source", "endpoint"}:
                return CONTRACT_MISMATCH_FAILURE_CODE
            variants = endpoint.get("variants")
            expected_variants = expected_endpoint.get("variants")
            if not isinstance(variants, list) or any(
                not isinstance(item, str) for item in variants
            ):
                return CONTRACT_MISMATCH_FAILURE_CODE
            if len(variants) != len(set(variants)):
                return CONTRACT_MISMATCH_FAILURE_CODE
            if not isinstance(expected_variants, list):
                raise GrammarStdlibT30Error("sealed F4 variants contract is invalid")
            alias_mismatch |= _same_items_out_of_order(variants, expected_variants)
            if not set(variants).issubset(set(expected_variants)):
                if set(variants).issubset(_known_task_symbol_strings(task)):
                    alias_mismatch = True
                else:
                    return "invented_symbol"
    return CONTRACT_MISMATCH_FAILURE_CODE if alias_mismatch else None


def _review_json_contract_failure(task: Mapping[str, Any], value: Any) -> str | None:
    if KNOWN_SURFACE_ALIASES_ARE_CONTRACT_MISMATCH:
        return _review_json_contract_failure_with_aliases(task, value)
    if not isinstance(value, Mapping):
        return CONTRACT_MISMATCH_FAILURE_CODE
    for key, allowed in (
        ("top_levels", TOP_LEVELS),
        ("stdlib_members", STDLIB_MEMBERS),
        ("stdlib_settings", STDLIB_SETTINGS),
    ):
        items = value.get(key)
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            return CONTRACT_MISMATCH_FAILURE_CODE
        if not set(items).issubset(allowed):
            return "invented_symbol"
    if task["family"] == "F-6":
        declarations = value.get("declarations")
        relationships = value.get("relationships")
        if not isinstance(declarations, list) or any(
            not isinstance(item, Mapping)
            or set(item) != {"kind", "name"}
            or item.get("kind") not in TOP_LEVELS
            or not isinstance(item.get("name"), str)
            or not item["name"]
            for item in declarations
        ):
            return "invented_symbol"
        if (
            not isinstance(relationships, list)
            or any(not isinstance(item, str) for item in relationships)
            or not set(relationships).issubset(RELATIONSHIP_LABELS)
        ):
            return "invented_symbol"
        fields = value.get("catalog_fields")
        if fields is not None and (
            not isinstance(fields, list)
            or any(
                not isinstance(item, Mapping)
                or item.get("domain") not in {"implicit", "external-enum", "open"}
                for item in fields
            )
        ):
            return "invented_symbol"
        expected_names = {item["name"] for item in task["expected_json"].get("declarations", [])}
        if any(item["name"] not in expected_names for item in declarations):
            return "invented_symbol"
        expected_fields = {item["name"] for item in task["expected_json"].get("catalog_fields", [])}
        if fields is not None and any(item.get("name") not in expected_fields for item in fields):
            return "invented_symbol"
    if task["family"] == "F-4":
        endpoint = value.get("endpoint")
        expected_endpoint = task["expected_json"]["endpoint"]
        if not isinstance(endpoint, Mapping):
            return CONTRACT_MISMATCH_FAILURE_CODE
        for key in ("requested", "selected", "variant"):
            item = endpoint.get(key)
            if item is not None and item != expected_endpoint.get(key):
                return "invented_symbol"
    return None


def _coverage_from_review_json(
    task: Mapping[str, Any], value: Mapping[str, Any]
) -> dict[str, list[str]]:
    result = _empty_coverage()
    for field in MODEL_JSON_COVERAGE_FIELDS:
        result[field] = list(value[field])
    if "stdlib_modules" in COVERAGE_FIELDS:
        result["stdlib_modules"] = _unique(
            member.removeprefix("std.").split(".", 1)[0] for member in result["stdlib_members"]
        )
        if result["stdlib_settings"] and "time" not in result["stdlib_modules"]:
            result["stdlib_modules"].append("time")
    if "interaction_classes" in COVERAGE_FIELDS:
        result["interaction_classes"] = _declared_interaction_classes(task)
    return result


def _source_code_only(source: str) -> str:
    """Mask literals/comments before deterministic stdlib surface inspection."""

    def mask(match: re.Match[str]) -> str:
        return "".join("\n" if char == "\n" else " " for char in match.group(0))

    value = re.sub(r'"(?:\\.|[^"\\])*"', mask, source)
    value = re.sub(r"//[^\n]*|/\*.*?\*/", mask, value, flags=re.S)
    return value


def _declaration_bodies(
    source: str, kinds: tuple[str, ...], *, name_suffix: str | None = None
) -> Iterator[str]:
    pattern = re.compile(
        rf"\b(?:{'|'.join(re.escape(kind) for kind in kinds)})\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\b"
    )
    for match in pattern.finditer(source):
        if name_suffix is not None and not match.group("name").endswith(name_suffix):
            continue
        opening = source.find("{", match.end())
        if opening < 0:
            continue
        depth = 0
        for index in range(opening, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    yield source[opening + 1 : index]
                    break


def _source_symbol_failure(source: str) -> str | None:
    """Classify only deterministic registry/nature errors; leave all else to the oracle."""

    code = _source_code_only(source)
    known_by_module = {
        module: {
            member
            for item in STDLIB_MEMBERS
            if "." in item
            for candidate_module, member in [item.split(".", 1)]
            if candidate_module == module
        }
        for module in ("time", "codec", "text")
    }
    pure_references = re.findall(
        r"\bstd\.([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", code
    )
    ambient_references = re.findall(r"(?<![A-Za-z0-9_.])time\.([A-Za-z_][A-Za-z0-9_]*)\b", code)
    capabilities = re.findall(r"\bneeds\s+([A-Za-z_][A-Za-z0-9_]*)\b", code)

    if any(module not in known_by_module for module, _member in pure_references):
        return "invented_symbol"
    if any(
        member not in known_by_module[module]
        for module, member in pure_references
        if module in known_by_module
    ):
        return "invented_symbol"
    if any(member not in known_by_module["time"] for member in ambient_references):
        return "invented_symbol"
    if any(capability not in known_by_module for capability in capabilities):
        return "invented_symbol"
    for body in _declaration_bodies(code, ("settings",), name_suffix=".time"):
        keys = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", body)
        if any(key != "timezone" for key in keys):
            return "invented_symbol"
    if any(module == "time" for module, _member in pure_references) or any(
        capability in {"codec", "text"} for capability in capabilities
    ):
        return "stdlib_nature_mismatch"
    for body in _declaration_bodies(code, ("endpoint", "property")):
        if re.search(r"(?<![A-Za-z0-9_.])time\.[A-Za-z_][A-Za-z0-9_]*\b", body) and not re.search(
            r"\bneeds\s+time\b", body
        ):
            return "ambient_capability_mismatch"
    return None


def score_candidate(
    task: Mapping[str, Any],
    response: Mapping[str, Any],
    truth_task: Mapping[str, Any],
    metis_root: Path,
    node_path: Path,
) -> dict[str, Any]:
    text = response.get("text")
    if not isinstance(text, str) or not text:
        raise GrammarStdlibT30Error("empty worker candidate")
    failure: str | None = None
    observed: dict[str, Any] | None = None
    observed_coverage = _empty_coverage()
    if task["task_mode"] == "source_output":
        source, failure = _extract_source(text)
        if source is not None:
            if CLASSIFY_SOURCE_SYMBOL_FAILURES and failure is None:
                failure = _source_symbol_failure(source)
            if failure is None:
                try:
                    with oracle.grammar_stdlib_oracle_session(
                        metis_root=metis_root, node_path=node_path
                    ) as session:
                        observed, envelope = _validate_source_envelope(
                            task,
                            source,
                            metis_root,
                            node_path,
                            session,
                            expected_ok=True,
                        )
                        observed_coverage = _coverage_for_task(
                            task, envelope["result"]["ast"]["inventory"]
                        )
                except (
                    GrammarStdlibT30Error,
                    d18.GrammarStdlibAccuracyError,
                    oracle.GrammarStdlibOracleError,
                ):
                    failure = "grammar_stdlib_oracle_rejected_candidate"
        correct = failure is None and observed == truth_task["target"].get("expected")
    else:
        value, failure = safe._extract_json(text)
        expected_hash = canonical_hash(task["expected_json"])
        if expected_hash != truth_task["target"].get("expected_json_sha256"):
            raise GrammarStdlibT30Error("T30 JSON target differs from sealed truth")
        if failure is None and value is not None:
            failure = _review_json_contract_failure(task, value)
        correct = (
            failure is None
            and value is not None
            and canonical_hash(value) == expected_hash
            and _json_key_order_matches(value, task["expected_json"])
        )
        if (
            failure is None
            and value is not None
            and not _json_key_order_matches(value, task["expected_json"])
        ):
            failure = CONTRACT_MISMATCH_FAILURE_CODE
        if isinstance(value, Mapping) and failure not in {
            "invented_symbol",
            "stdlib_nature_mismatch",
            CONTRACT_MISMATCH_FAILURE_CODE,
        }:
            observed_coverage = _coverage_from_review_json(task, value)
        observed = None if value is None else {"json": value, "json_sha256": canonical_hash(value)}
    automatic = task["family"] in {"F-1", "F-2", "F-3", "F-4"}
    semantic_correct: bool | None = correct if automatic else None
    if task["task_mode"] == "exact_json_review" and failure not in {
        None,
        "invented_symbol",
        "stdlib_nature_mismatch",
        CONTRACT_MISMATCH_FAILURE_CODE,
    }:
        failure = "json_format_mismatch"
    elif not correct and failure is None:
        failure = "human_review_mismatch" if not automatic else "semantic_mismatch"
    harmless = {
        None,
        "semantic_mismatch",
        "human_review_mismatch",
        "json_format_mismatch",
        CONTRACT_MISMATCH_FAILURE_CODE,
    }
    return {
        "task_id": task["task_id"],
        "family": task["family"],
        "task_mode": task["task_mode"],
        "authority_tier": task["authority_tier"],
        "independent_root": task["provenance_roots"]["independent"],
        "mechanical_match": correct,
        "semantic_correct": semantic_correct,
        "final_human_review_required": task["family"] in FINAL_HUMAN_REVIEW,
        "final_human_review_kind": FINAL_HUMAN_REVIEW.get(task["family"]),
        "critical_failure": failure not in harmless,
        "failure_code": failure,
        "candidate_sha256": raw_hash(text.encode()),
        "observed": observed,
        "observed_coverage": observed_coverage,
        "peak_metal_gb": response["peak_metal_gb"],
    }


def summarize(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if len(rows) > TASK_COUNT:
        raise GrammarStdlibT30Error("T30 observation roster is oversized")
    return {
        "tasks_in": TASK_COUNT,
        "tasks_out": len(rows),
        "tasks_distinct": len({row["task_id"] for row in rows}),
        "gaps": TASK_COUNT - len(rows),
        "semantic_correct": sum(row["semantic_correct"] is True for row in rows),
        "semantic_denominator": sum(row["semantic_correct"] is not None for row in rows),
        "provisional_exact_match": sum(bool(row["mechanical_match"]) for row in rows),
        "human_review_pending": sum(bool(row["final_human_review_required"]) for row in rows),
        "critical_failure": sum(bool(row["critical_failure"]) for row in rows),
        "family": {
            family: sum(row["semantic_correct"] is True for row in rows if row["family"] == family)
            for family in FAMILIES
        },
        "family_denominator": {
            family: sum(
                row["semantic_correct"] is not None for row in rows if row["family"] == family
            )
            for family in FAMILIES
        },
        "family_provisional": {
            family: sum(bool(row["mechanical_match"]) for row in rows if row["family"] == family)
            for family in FAMILIES
        },
        "automatic": {
            "correct": sum(
                row["semantic_correct"] is True
                for row in rows
                if row["family"] in {"F-1", "F-2", "F-3", "F-4"}
            ),
            "denominator": sum(
                row["semantic_correct"] is not None
                for row in rows
                if row["family"] in {"F-1", "F-2", "F-3", "F-4"}
            ),
        },
    }


def gate_arithmetic(
    base: list[Mapping[str, Any]], adapter: list[Mapping[str, Any]]
) -> dict[str, Any]:
    if (
        len(base) != TASK_COUNT
        or len(adapter) != TASK_COUNT
        or [row["task_id"] for row in base] != [row["task_id"] for row in adapter]
    ):
        raise GrammarStdlibT30Error("paired T30 roster differs")
    left, right = summarize(base), summarize(adapter)
    regressions = [
        a["task_id"]
        for a, b in zip(base, adapter, strict=True)
        if a["semantic_correct"] is True and b["semantic_correct"] is False
    ]
    mechanical_regressions = [
        a["task_id"]
        for a, b in zip(base, adapter, strict=True)
        if bool(a["mechanical_match"]) and not bool(b["mechanical_match"])
    ]
    automatic_families = ("F-1", "F-2", "F-3", "F-4")
    veto_codes = {"grammar_stdlib_oracle_rejected_candidate"}
    gates = {
        # F2/F5/F6 need a separate final human judgment.  These are explicitly
        # provisional exact-match indicators until their fifteen IDs are reviewed.
        "final_adapter_29_of_30_provisional": right["provisional_exact_match"]
        >= THRESHOLDS["adapter_semantic_total_min"],
        "final_family_floor_provisional": all(
            right["family_provisional"][family] >= THRESHOLDS["family_semantic_min"]
            for family in FAMILIES
        ),
        "automatic_semantic_total": right["automatic"]["correct"]
        >= THRESHOLDS["automatic_semantic_total_min"],
        "automatic_semantic_denominator": right["automatic"]["denominator"]
        == THRESHOLDS["automatic_semantic_denominator"],
        "automatic_family_floor": all(
            right["family_denominator"][family] == 5
            and right["family"][family] >= THRESHOLDS["automatic_family_min"]
            for family in automatic_families
        ),
        "critical_invented_unauthorized_tool_retrieval_veto": right["critical_failure"]
        <= THRESHOLDS["critical_max"],
        "unauthorized_tool_retrieval_veto": not any(
            row["failure_code"] in veto_codes for row in adapter
        ),
        "complete": right["gaps"] == 0 and right["tasks_distinct"] == TASK_COUNT,
        "no_paired_regression": not regressions and not mechanical_regressions,
    }
    pending = [row["task_id"] for row in adapter if row["final_human_review_required"]]
    return {
        "verdict": PRE_REVIEW_VERDICT if all(gates.values()) else DIAGNOSE_VERDICT,
        "authority_tier": "diagnostic_only",
        "base": left,
        "adapter": right,
        "gates": gates,
        "paired_regressions": regressions,
        "paired_mechanical_regressions": mechanical_regressions,
        "review_required": {
            "authority_tier": "human_review_required",
            "task_ids": pending,
            "count": len(pending),
            "families": FINAL_HUMAN_REVIEW,
            "training_authority": False,
        },
        "training_authorized": False,
        "delta_qlora_authorized": False,
    }


def _directory_identity(item: os.stat_result) -> tuple[int, int, int]:
    return item.st_dev, item.st_ino, item.st_mode


def _direct_directory(path: Path, label: str) -> tuple[int, tuple[int, int, int]]:
    try:
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
    except OSError as error:
        raise GrammarStdlibT30Error(f"{label} is unavailable") from error
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISDIR(before.st_mode)
        or not stat.S_ISDIR(opened.st_mode)
        or _directory_identity(before) != _directory_identity(opened)
    ):
        os.close(descriptor)
        raise GrammarStdlibT30Error(f"{label} is not a direct stable directory")
    return descriptor, _directory_identity(opened)


def _mkdir_direct(path: Path, label: str) -> None:
    try:
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
    except FileExistsError as error:
        raise GrammarStdlibT30Error(f"{label} already exists") from error
    descriptor, _identity = _direct_directory(path, label)
    os.close(descriptor)


def _assert_ancestors(run_dir: Path, *, allow_missing: bool) -> None:
    if run_dir != _run_dir():
        raise GrammarStdlibT30Error("run directory escaped fixed T30 root")
    for path, label in (
        (PROJECT_ROOT, "project root"),
        (PROJECT_ROOT / "artifacts", "artifact root"),
        (PROJECT_ROOT / "artifacts/grammar-stdlib-accuracy", "grammar artifact root"),
        (RUN_ROOT, "T30 artifact root"),
    ):
        if path.exists() or path.is_symlink():
            descriptor, _identity = _direct_directory(path, label)
            os.close(descriptor)
        elif allow_missing:
            _mkdir_direct(path, label)
        else:
            raise GrammarStdlibT30Error(f"{label} is unavailable")


def _write_ocl(directory: Path, name: str, raw: bytes) -> Path:
    """O_EXCL/no-symlink publication; never clobbers an existing receipt/output."""
    if not raw or name not in {"attempt.json", "candidates.jsonl", "report.json"}:
        raise GrammarStdlibT30Error("invalid T30 output name or payload")
    descriptor, identity = _direct_directory(directory, f"T30 output directory {directory.name}")
    fd: int | None = None
    try:
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=descriptor,
        )
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise GrammarStdlibT30Error("T30 output write made no progress")
            view = view[count:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.fsync(descriptor)
        published = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(published.st_mode)
            or published.st_nlink != 1
            or published.st_size != len(raw)
            or _directory_identity(os.fstat(descriptor)) != identity
            or stat.S_IMODE(published.st_mode) != 0o600
        ):
            raise GrammarStdlibT30Error("T30 output publication identity drift")
    except OSError as error:
        raise GrammarStdlibT30Error(f"cannot publish T30 {name} without clobber") from error
    finally:
        if fd is not None:
            os.close(fd)
        os.close(descriptor)
    return directory / name


def _write_manifest_once(path: Path, value: Mapping[str, Any]) -> Path:
    """Publish one canonical tracked manifest without a replace/clobber window."""

    if path not in {TRUTH_PATH, FREEZE_PATH, EVIDENCE_PATH, ADJUDICATION_PATH}:
        raise GrammarStdlibT30Error("invalid T30 manifest output path")
    raw = safe.canonical_bytes(value) + b"\n"
    descriptor, identity = _direct_directory(path.parent, "T30 manifest directory")
    fd: int | None = None
    try:
        fd = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o644,
            dir_fd=descriptor,
        )
        os.fchmod(fd, 0o644)
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise GrammarStdlibT30Error("T30 manifest write made no progress")
            view = view[count:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.fsync(descriptor)
        published = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(published.st_mode)
            or published.st_nlink != 1
            or published.st_size != len(raw)
            or stat.S_IMODE(published.st_mode) != 0o644
            or _directory_identity(os.fstat(descriptor)) != identity
        ):
            raise GrammarStdlibT30Error("T30 manifest publication identity drift")
    except OSError as error:
        raise GrammarStdlibT30Error(
            f"cannot publish T30 manifest {path.name} without clobber"
        ) from error
    finally:
        if fd is not None:
            os.close(fd)
        os.close(descriptor)
    return path


def _prepare_run(
    run_dir: Path,
    freeze_value: Mapping[str, Any],
    head: str,
    tree: str,
    requests: list[Mapping[str, Any]],
) -> None:
    _assert_ancestors(run_dir, allow_missing=True)
    _mkdir_direct(run_dir, "T30 run directory")
    for name in ("base", "adapter"):
        _mkdir_direct(run_dir / name, f"T30 run child {name}")
    receipt = {
        "schema_version": 1,
        "attempt_id": ATTEMPT_NONCE,
        "status": "started_before_model_output",
        "head": head,
        "tree": tree,
        "freeze_sha256": freeze_value["freeze_sha256"],
        "base_requests": TASK_COUNT,
        "adapter_requests": TASK_COUNT,
        "requests_sha256": canonical_hash(requests),
        "request_ids_sha256": canonical_hash([row["request_id"] for row in requests]),
        "base_worker_command": _worker_command(False),
        "adapter_worker_command": _worker_command(True),
        "runtime_identities_sha256": canonical_hash(freeze_value["runtime_identities"]),
        "generation": GENERATION,
        "model_outputs_observed": False,
        "training_authorized": False,
        "delta_qlora_authorized": False,
    }
    receipt["attempt_sha256"] = canonical_hash(receipt)
    _write_ocl(run_dir, "attempt.json", safe.canonical_bytes(receipt) + b"\n")


def _attempt_receipt(
    run_dir: Path,
    freeze_value: Mapping[str, Any],
    head: str,
    tree: str,
    requests: list[Mapping[str, Any]],
) -> dict[str, Any]:
    value, raw = _load(run_dir / "attempt.json", "T30 attempt receipt")
    _self_hash(value, "attempt_sha256")
    required = {
        "schema_version",
        "attempt_id",
        "status",
        "head",
        "tree",
        "freeze_sha256",
        "base_requests",
        "adapter_requests",
        "requests_sha256",
        "request_ids_sha256",
        "base_worker_command",
        "adapter_worker_command",
        "runtime_identities_sha256",
        "generation",
        "model_outputs_observed",
        "training_authorized",
        "delta_qlora_authorized",
        "attempt_sha256",
    }
    if (
        set(value) != required
        or value.get("schema_version") != 1
        or value.get("attempt_id") != ATTEMPT_NONCE
        or value.get("status") != "started_before_model_output"
        or value.get("head") != head
        or value.get("tree") != tree
        or value.get("freeze_sha256") != freeze_value.get("freeze_sha256")
        or value.get("base_requests") != TASK_COUNT
        or value.get("adapter_requests") != TASK_COUNT
        or value.get("requests_sha256") != canonical_hash(requests)
        or value.get("request_ids_sha256")
        != canonical_hash([row["request_id"] for row in requests])
        or value.get("base_worker_command") != _worker_command(False)
        or value.get("adapter_worker_command") != _worker_command(True)
        or value.get("runtime_identities_sha256")
        != canonical_hash(freeze_value["runtime_identities"])
        or value.get("generation") != GENERATION
        or value.get("model_outputs_observed") is not False
        or value.get("training_authorized") is not False
        or value.get("delta_qlora_authorized") is not False
    ):
        raise GrammarStdlibT30Error("T30 attempt receipt drift")
    return {
        "path": str((run_dir / "attempt.json").relative_to(PROJECT_ROOT)),
        "bytes": len(raw),
        "sha256": raw_hash(raw),
        "attempt_sha256": value["attempt_sha256"],
    }


def _worker_command(adapter: bool) -> list[str]:
    command = [
        str(qlora.SANDBOX_EXEC),
        "-p",
        qlora.EVALUATION_SANDBOX_POLICY,
        str(QUALIFICATION_PYTHON),
        str(Path(qlora.__file__).resolve()),
        "worker",
        "--model",
        str(qlora.BASE_CHECKPOINT),
    ]
    if adapter:
        command.extend(("--adapter", str(ADAPTER_PATH)))
    return command


def _verify_responses(tasks: list[Mapping[str, Any]], rows: list[Mapping[str, Any]]) -> None:
    if len(tasks) != TASK_COUNT or len(rows) != TASK_COUNT:
        raise GrammarStdlibT30Error("T30 worker response count differs")
    for task, row in zip(tasks, rows, strict=True):
        if (
            set(row) != {"request_id", "text", "peak_metal_gb"}
            or row.get("request_id") != task["task_id"]
            or not isinstance(row.get("text"), str)
            or not row["text"]
            or type(row.get("peak_metal_gb")) not in (int, float)
            or not 0 <= float(row["peak_metal_gb"]) <= qlora.LIMITS["metal_gb"]
        ):
            raise GrammarStdlibT30Error("T30 worker response roster/schema drift")


def _candidates(tasks: list[Mapping[str, Any]], rows: list[Mapping[str, Any]]) -> bytes:
    return b"".join(
        safe.canonical_bytes(
            {"task_id": task["task_id"], "text": row["text"], "peak_metal_gb": row["peak_metal_gb"]}
        )
        + b"\n"
        for task, row in zip(tasks, rows, strict=True)
    )


def _read_candidates(path: Path, tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    raw = safe._read_regular(path, "T30 candidates", 32 * 1024 * 1024)
    lines = raw.splitlines()
    if len(lines) != TASK_COUNT:
        raise GrammarStdlibT30Error("T30 candidate count differs")
    result: list[dict[str, Any]] = []
    for task, line in zip(tasks, lines, strict=True):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise GrammarStdlibT30Error("T30 candidate row is invalid JSON") from error
        if (
            not isinstance(value, dict)
            or set(value) != {"task_id", "text", "peak_metal_gb"}
            or value.get("task_id") != task["task_id"]
            or not isinstance(value.get("text"), str)
            or not value["text"]
            or type(value.get("peak_metal_gb")) not in (int, float)
            or line != safe.canonical_bytes(value)
        ):
            raise GrammarStdlibT30Error("T30 candidate row contract drift")
        result.append(
            {
                "request_id": task["task_id"],
                "text": value["text"],
                "peak_metal_gb": value["peak_metal_gb"],
            }
        )
    return result


def _candidate_output_identities(run_dir: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for label in ("base", "adapter"):
        path = run_dir / label / "candidates.jsonl"
        raw = safe._read_regular(path, f"T30 {label} candidates", 32 * 1024 * 1024)
        result[label] = {
            "path": str(path.relative_to(PROJECT_ROOT)),
            "bytes": len(raw),
            "sha256": raw_hash(raw),
        }
    return result


def _verify_run_roster(run_dir: Path, *, complete: bool) -> None:
    _assert_ancestors(run_dir, allow_missing=False)
    expected = {
        run_dir / "attempt.json",
        run_dir / "base/candidates.jsonl",
        run_dir / "adapter/candidates.jsonl",
    }
    if complete:
        expected.add(run_dir / "report.json")
    found: set[Path] = set()
    directories: set[Path] = set()
    for path in run_dir.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise GrammarStdlibT30Error("T30 run contains symlink")
        if stat.S_ISDIR(metadata.st_mode):
            directories.add(path)
        elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
            found.add(path)
        else:
            raise GrammarStdlibT30Error("T30 run contains special/linked file")
    if found != expected or directories != {run_dir / "base", run_dir / "adapter"}:
        raise GrammarStdlibT30Error("T30 run artifact roster differs")


def run(args: argparse.Namespace) -> int:
    freeze_value, freeze_raw = _load(FREEZE_PATH, "T30 freeze")
    if _tracked_record(str(FREEZE_PATH.relative_to(PROJECT_ROOT)))["sha256"] != raw_hash(
        freeze_raw
    ):
        raise GrammarStdlibT30Error("T30 freeze is not committed")
    head, tree, remote_ref = _published(str(freeze_value["remote"]))
    if remote_ref != freeze_value["remote_ref"]:
        raise GrammarStdlibT30Error("T30 remote reference drift")
    run_dir = _verify_freeze(freeze_value, head)
    tasks, truth_value = _verify_frozen_inputs(
        freeze_value, Path(args.metis_root), Path(args.node_path)
    )
    if run_dir.exists() or run_dir.is_symlink():
        raise GrammarStdlibT30Error("T30 attempt already exists; retries are forbidden")
    qlora._metal_jit_sandbox_canary()
    requests = _request_batch(tasks)
    _verify_bound(list(freeze_value["bound_inputs"]))
    _prepare_run(run_dir, freeze_value, head, tree, requests)
    attempt = _attempt_receipt(run_dir, freeze_value, head, tree, requests)
    observations: dict[str, list[dict[str, Any]]] = {}
    outputs: dict[str, dict[str, Any]] = {}
    truth_by_id = {row["task_id"]: row for row in truth_value["tasks"]}
    for label, adapter in (("base", False), ("adapter", True)):
        responses = qlora._bounded_worker(
            _worker_command(adapter), requests, qlora.LIMITS["hours"] * 3600
        )
        _verify_responses(tasks, responses)
        candidate = _candidates(tasks, responses)
        path = _write_ocl(run_dir / label, "candidates.jsonl", candidate)
        outputs[label] = {
            "path": str(path.relative_to(PROJECT_ROOT)),
            "bytes": len(candidate),
            "sha256": raw_hash(candidate),
        }
        observations[label] = [
            score_candidate(
                task,
                response,
                truth_by_id[task["task_id"]],
                Path(args.metis_root),
                Path(args.node_path),
            )
            for task, response in zip(tasks, responses, strict=True)
        ]
    post_head, post_tree, post_remote_ref = _published(str(freeze_value["remote"]))
    if (post_head, post_tree, post_remote_ref) != (head, tree, remote_ref):
        raise GrammarStdlibT30Error("published T30 preimage changed during inference")
    _verify_bound(list(freeze_value["bound_inputs"]))
    _verify_run_roster(run_dir, complete=False)
    decision = gate_arithmetic(observations["base"], observations["adapter"])
    report = {
        "schema_version": 1,
        "status": "complete",
        "authority_tier": "diagnostic_only",
        "head": head,
        "tree": tree,
        "freeze_sha256": freeze_value["freeze_sha256"],
        "attempt_nonce": ATTEMPT_NONCE,
        "attempt_receipt": attempt,
        "outputs": outputs,
        "observations": observations,
        "decision": decision,
        "model_outputs_observed": True,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "nonclaims": NONCLAIMS,
    }
    report["report_sha256"] = canonical_hash(report)
    _write_ocl(run_dir, "report.json", safe.canonical_bytes(report) + b"\n")
    _verify_run_roster(run_dir, complete=True)
    print(
        json.dumps(
            {"event": "grammar_stdlib_t30_run", "verdict": decision["verdict"]}, sort_keys=True
        )
    )
    return 0 if decision["verdict"].endswith("PASS") else 1


def _rescore_run(
    tasks: list[Mapping[str, Any]],
    truth_value: Mapping[str, Any],
    run_dir: Path,
    metis_root: Path,
    node_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Recompute all candidate observations from raw outputs and pinned truth."""

    truth_by_id = {row["task_id"]: row for row in truth_value["tasks"]}
    observations = {
        label: [
            score_candidate(
                task,
                row,
                truth_by_id[task["task_id"]],
                metis_root,
                node_path,
            )
            for task, row in zip(
                tasks,
                _read_candidates(run_dir / label / "candidates.jsonl", tasks),
                strict=True,
            )
        ]
        for label in ("base", "adapter")
    }
    return observations, gate_arithmetic(observations["base"], observations["adapter"])


def _public_observations(
    observations: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    keys = (
        "task_id",
        "family",
        "task_mode",
        "authority_tier",
        "independent_root",
        "mechanical_match",
        "semantic_correct",
        "critical_failure",
        "failure_code",
        "candidate_sha256",
        "observed",
        "observed_coverage",
    )
    return {
        label: [{key: row[key] for key in keys} for row in values]
        for label, values in observations.items()
    }


def _verify_report_and_rescore(
    *,
    freeze_value: Mapping[str, Any],
    run_dir: Path,
    tasks: list[Mapping[str, Any]],
    truth_value: Mapping[str, Any],
    metis_root: Path,
    node_path: Path,
    current_head: str,
    expected_run_identity: tuple[str, str] | None,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Verify the immutable run report and independently rescore raw candidates."""

    _verify_run_roster(run_dir, complete=True)
    report, report_raw = _load(run_dir / "report.json", "T30 report")
    _self_hash(report, "report_sha256")
    run_head = report.get("head")
    run_tree = report.get("tree")
    if not isinstance(run_head, str) or not isinstance(run_tree, str):
        raise GrammarStdlibT30Error("T30 report commit identity is invalid")
    if expected_run_identity is not None:
        if (run_head, run_tree) != expected_run_identity:
            raise GrammarStdlibT30Error("T30 report execution identity drift")
    else:
        if (
            str(_pinned_git(PROJECT_ROOT, "rev-parse", f"{run_head}^{{commit}}")) != run_head
            or str(_pinned_git(PROJECT_ROOT, "rev-parse", f"{run_head}^{{tree}}")) != run_tree
        ):
            raise GrammarStdlibT30Error("T30 report commit identity drift")
        _pinned_git(
            PROJECT_ROOT,
            "merge-base",
            "--is-ancestor",
            str(freeze_value["preimage_commit"]),
            run_head,
        )
        _pinned_git(PROJECT_ROOT, "merge-base", "--is-ancestor", run_head, current_head)
    requests = _request_batch(tasks)
    attempt = _attempt_receipt(run_dir, freeze_value, run_head, run_tree, requests)
    required = {
        "schema_version",
        "status",
        "authority_tier",
        "head",
        "tree",
        "freeze_sha256",
        "attempt_nonce",
        "attempt_receipt",
        "outputs",
        "observations",
        "decision",
        "model_outputs_observed",
        "training_authorized",
        "delta_qlora_authorized",
        "nonclaims",
        "report_sha256",
    }
    if (
        set(report) != required
        or report_raw != safe.canonical_bytes(report) + b"\n"
        or report.get("schema_version") != 1
        or report.get("status") != "complete"
        or report.get("authority_tier") != "diagnostic_only"
        or report.get("freeze_sha256") != freeze_value["freeze_sha256"]
        or report.get("attempt_nonce") != ATTEMPT_NONCE
        or report.get("attempt_receipt") != attempt
        or report.get("outputs") != _candidate_output_identities(run_dir)
        or report.get("model_outputs_observed") is not True
        or report.get("training_authorized") is not False
        or report.get("delta_qlora_authorized") is not False
        or report.get("nonclaims") != NONCLAIMS
    ):
        raise GrammarStdlibT30Error("T30 report lineage drift")
    observations, decision = _rescore_run(tasks, truth_value, run_dir, metis_root, node_path)
    if report.get("observations") != observations or report.get("decision") != decision:
        raise GrammarStdlibT30Error("T30 report differs from independent rescore")
    return report, observations, decision


def _evaluation_document(
    *,
    freeze_value: Mapping[str, Any],
    freeze_raw: bytes,
    report: Mapping[str, Any],
    observations: Mapping[str, list[Mapping[str, Any]]],
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": 1,
        "evidence_id": EVIDENCE_ID,
        "status": "verified_local_cooperative",
        "authority_tier": "diagnostic_only",
        "execution": {
            "head": report["head"],
            "tree": report["tree"],
            "freeze_sha256": freeze_value["freeze_sha256"],
            "freeze_file_sha256": raw_hash(freeze_raw),
            "report_sha256": report["report_sha256"],
            "run_dir": RUN_RELATIVE,
            "outputs": report["outputs"],
        },
        "observations": _public_observations(observations),
        "decision": decision,
        "model_outputs_observed": True,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "nonclaims": NONCLAIMS,
    }
    body["evaluation_sha256"] = canonical_hash(body)
    return body


def _require_exact_rescored_evaluation(
    evaluation: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    if evaluation != expected:
        raise GrammarStdlibT30Error("published T30 evaluation differs from fresh rescore")


def evidence(args: argparse.Namespace) -> int:
    if EVIDENCE_PATH.exists() or EVIDENCE_PATH.is_symlink():
        raise GrammarStdlibT30Error("evidence output already exists")
    freeze_value, freeze_raw = _load(FREEZE_PATH, "T30 freeze")
    if _tracked_record(str(FREEZE_PATH.relative_to(PROJECT_ROOT)))["sha256"] != raw_hash(
        freeze_raw
    ):
        raise GrammarStdlibT30Error("T30 freeze is not committed")
    head, tree, remote_ref = _published(str(freeze_value["remote"]))
    if remote_ref != freeze_value["remote_ref"]:
        raise GrammarStdlibT30Error("T30 remote reference drift")
    run_dir = _verify_freeze(freeze_value, head)
    tasks, truth_value = _verify_frozen_inputs(
        freeze_value, Path(args.metis_root), Path(args.node_path)
    )
    report, observations, decision = _verify_report_and_rescore(
        freeze_value=freeze_value,
        run_dir=run_dir,
        tasks=tasks,
        truth_value=truth_value,
        metis_root=Path(args.metis_root),
        node_path=Path(args.node_path),
        current_head=head,
        expected_run_identity=(head, tree),
    )
    body = _evaluation_document(
        freeze_value=freeze_value,
        freeze_raw=freeze_raw,
        report=report,
        observations=observations,
        decision=decision,
    )
    _write_manifest_once(EVIDENCE_PATH, body)
    print(
        json.dumps(
            {"event": "grammar_stdlib_t30_evidence", "verdict": decision["verdict"]}, sort_keys=True
        )
    )
    return 0 if decision["verdict"].endswith("PASS") else 1


def _load_review_receipt(path: Path, evaluation: Mapping[str, Any]) -> tuple[dict[str, Any], bytes]:
    value, raw = _load(path, "T30 human review receipt")
    required_ids = list(evaluation["decision"]["review_required"]["task_ids"])
    observations = {row["task_id"]: row for row in evaluation["observations"]["adapter"]}
    if (
        set(value)
        != {
            "schema_version",
            "review_id",
            "authority_tier",
            "reviewer_role",
            "evaluation_sha256",
            "reviews",
        }
        or value.get("schema_version") != 1
        or value.get("review_id") != HUMAN_REVIEW_ID
        or value.get("authority_tier") != "human_review_required"
        or value.get("reviewer_role") != "L0_frontier_coordinator"
        or value.get("evaluation_sha256") != evaluation.get("evaluation_sha256")
        or not isinstance(value.get("reviews"), list)
        or len(value["reviews"]) != HUMAN_REVIEW_COUNT
    ):
        raise GrammarStdlibT30Error("T30 human review receipt contract drift")
    if [row.get("task_id") for row in value["reviews"]] != required_ids:
        raise GrammarStdlibT30Error("T30 human review roster differs from preregistration")
    for row in value["reviews"]:
        if not isinstance(row, Mapping):
            raise GrammarStdlibT30Error("T30 human review row is invalid")
        task_id = str(row.get("task_id"))
        observation = observations.get(task_id)
        family = observation.get("family") if isinstance(observation, Mapping) else None
        expected_kind = FINAL_HUMAN_REVIEW.get(str(family))
        if (
            set(row)
            != {
                "task_id",
                "family",
                "review_kind",
                "candidate_sha256",
                "decision",
                "rationale_code",
                "rationale",
                "source",
            }
            or family not in FINAL_HUMAN_REVIEW
            or row.get("family") != family
            or row.get("review_kind") != expected_kind
            or row.get("candidate_sha256") != observation.get("candidate_sha256")
            or row.get("decision") not in {"ACCEPT", "REJECT", "UNCLEAR"}
            or not isinstance(row.get("rationale_code"), str)
            or not row["rationale_code"].startswith(str(family).replace("-", ""))
            or not isinstance(row.get("rationale"), str)
            or len(row["rationale"].strip()) < 20
            or row.get("source") != "direct_candidate_and_pinned_truth_review"
        ):
            raise GrammarStdlibT30Error("T30 human review row does not bind its candidate")
    return value, raw


def _successful_coverage_gate(
    successful: list[Mapping[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, bool]]:
    """Credit only successful rows and enforce the ratified occurrence floor."""

    counts = {
        field: Counter(value for row in successful for value in row["observed_coverage"][field])
        for field in COVERAGE_FIELDS
    }
    coverage = {field: sorted(field_counts) for field, field_counts in counts.items()}
    minimum = POLICY_COVERAGE_GATE.get("minimum_successful_occurrences_each", 1)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        raise GrammarStdlibT30Error("T30 successful coverage occurrence floor is invalid")
    gates = {
        FINAL_COVERAGE_GATE_NAMES[field]: set(coverage[field]) == denominator
        and all(counts[field][value] >= minimum for value in denominator)
        for field, denominator in _coverage_domains().items()
    }
    return coverage, gates


def _final_adjudication(
    evaluation: Mapping[str, Any],
    reviews: Mapping[str, Any],
    freeze_value: Mapping[str, Any],
) -> dict[str, Any]:
    review_by_id = {row["task_id"]: row for row in reviews["reviews"]}
    rows = evaluation["observations"]["adapter"]
    if not isinstance(rows, list) or len(rows) != TASK_COUNT:
        raise GrammarStdlibT30Error("T30 adapter evidence roster is incomplete")
    final_rows: list[dict[str, Any]] = []
    for row in rows:
        family = str(row["family"])
        review = review_by_id.get(row["task_id"])
        automatic_ok = row.get("semantic_correct") is True
        mechanical_ok = row.get("mechanical_match") is True
        if family in FINAL_HUMAN_REVIEW:
            success = (
                (automatic_ok if family == "F-2" else mechanical_ok)
                and review is not None
                and review["decision"] == "ACCEPT"
            )
        else:
            success = automatic_ok
        coverage = row.get("observed_coverage")
        if (
            not isinstance(coverage, Mapping)
            or set(coverage) != set(COVERAGE_FIELDS)
            or not all(isinstance(coverage.get(key), list) for key in COVERAGE_FIELDS)
            or any(
                any(not isinstance(item, str) for item in coverage[field])
                or not set(coverage[field]).issubset(allowed)
                for field, allowed in _coverage_domains().items()
            )
        ):
            raise GrammarStdlibT30Error("T30 observed coverage is invalid")
        final_rows.append(
            {
                "task_id": row["task_id"],
                "family": family,
                "success": success,
                "automatic_semantic_correct": row.get("semantic_correct"),
                "mechanical_match": mechanical_ok,
                "review_decision": None if review is None else review["decision"],
                "candidate_sha256": row["candidate_sha256"],
                "observed_coverage": coverage,
            }
        )
    successful = [row for row in final_rows if row["success"]]
    coverage, coverage_gates = _successful_coverage_gate(successful)
    family = {
        name: sum(row["success"] for row in final_rows if row["family"] == name)
        for name in FAMILIES
    }
    prior = evaluation["decision"]
    restore = freeze_value["runtime_identities"]["adapter_off_restore"]
    gates = {
        "adapter_semantic_29_of_30": len(successful) >= THRESHOLDS["adapter_semantic_total_min"],
        "family_floor_4_of_5": all(
            family[name] >= THRESHOLDS["family_semantic_min"] for name in FAMILIES
        ),
        "human_reviews_complete": len(review_by_id) == HUMAN_REVIEW_COUNT
        and all(row["decision"] in {"ACCEPT", "REJECT"} for row in reviews["reviews"]),
        "critical_veto_clear": prior["adapter"]["critical_failure"] == 0,
        "no_paired_regression": not prior["paired_regressions"]
        and not prior["paired_mechanical_regressions"],
        "complete": prior["gates"]["complete"],
        "automatic_gate": prior["gates"]["automatic_semantic_total"]
        and prior["gates"]["automatic_semantic_denominator"]
        and prior["gates"]["automatic_family_floor"],
        "adapter_off_exact_restore": restore.get("exact_candidate_restore") is True,
    }
    gates = {**gates, **coverage_gates}
    verdict = PASS_VERDICT if all(gates.values()) else DIAGNOSE_VERDICT
    return {
        "verdict": verdict,
        "authority_tier": "local_held_out_grammar_stdlib",
        "semantic_correct": len(successful),
        "semantic_denominator": TASK_COUNT,
        "family": family,
        "coverage": coverage,
        "gates": gates,
        "final_tasks": final_rows,
        "training_authorized": False,
        "delta_qlora_authorized": False,
    }


def adjudicate(args: argparse.Namespace) -> int:
    if ADJUDICATION_PATH.exists() or ADJUDICATION_PATH.is_symlink():
        raise GrammarStdlibT30Error("adjudication output already exists")
    if args.reviews is None:
        raise GrammarStdlibT30Error("adjudication requires an explicit human review receipt")
    evaluation, evaluation_raw = _load(EVIDENCE_PATH, "T30 evaluation")
    _self_hash(evaluation, "evaluation_sha256")
    if (
        _tracked_record(str(EVIDENCE_PATH.relative_to(PROJECT_ROOT)))["sha256"]
        != raw_hash(evaluation_raw)
        or evaluation_raw != safe.canonical_bytes(evaluation) + b"\n"
        or evaluation.get("status") != "verified_local_cooperative"
        or evaluation.get("model_outputs_observed") is not True
        or evaluation.get("training_authorized") is not False
        or evaluation.get("delta_qlora_authorized") is not False
        or evaluation.get("nonclaims") != NONCLAIMS
    ):
        raise GrammarStdlibT30Error("published T30 evaluation contract drift")
    freeze_value, freeze_raw = _load(FREEZE_PATH, "T30 freeze")
    if _tracked_record(str(FREEZE_PATH.relative_to(PROJECT_ROOT)))["sha256"] != raw_hash(
        freeze_raw
    ):
        raise GrammarStdlibT30Error("T30 freeze is not committed")
    head, _tree, remote_ref = _published(str(freeze_value["remote"]))
    if remote_ref != freeze_value["remote_ref"]:
        raise GrammarStdlibT30Error("T30 remote reference drift")
    run_dir = _verify_freeze(freeze_value, head)
    tasks, truth_value = _verify_frozen_inputs(
        freeze_value, Path(args.metis_root), Path(args.node_path)
    )
    report, observations, rescored_decision = _verify_report_and_rescore(
        freeze_value=freeze_value,
        run_dir=run_dir,
        tasks=tasks,
        truth_value=truth_value,
        metis_root=Path(args.metis_root),
        node_path=Path(args.node_path),
        current_head=head,
        expected_run_identity=None,
    )
    expected_evaluation = _evaluation_document(
        freeze_value=freeze_value,
        freeze_raw=freeze_raw,
        report=report,
        observations=observations,
        decision=rescored_decision,
    )
    _require_exact_rescored_evaluation(evaluation, expected_evaluation)
    reviews, review_raw = _load_review_receipt(Path(args.reviews), evaluation)
    decision = _final_adjudication(evaluation, reviews, freeze_value)
    body = {
        "schema_version": 1,
        "adjudication_id": ADJUDICATION_ID,
        "status": "final_local_adjudication",
        "authority_tier": "L0_frontier_human_review",
        "evaluation_sha256": evaluation["evaluation_sha256"],
        "evaluation_file_sha256": raw_hash(evaluation_raw),
        "freeze_sha256": freeze_value["freeze_sha256"],
        "review_receipt_sha256": raw_hash(review_raw),
        "reviews": reviews["reviews"],
        "decision": decision,
        "model_outputs_observed": True,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "nonclaims": NONCLAIMS,
    }
    body["adjudication_sha256"] = canonical_hash(body)
    _write_manifest_once(ADJUDICATION_PATH, body)
    print(
        json.dumps(
            {"event": "grammar_stdlib_t30_adjudication", "verdict": decision["verdict"]},
            sort_keys=True,
        )
    )
    return 0 if decision["verdict"].endswith("PASS_NO_RETRAIN") else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("mode", choices=("truth", "freeze", "run", "evidence", "adjudicate"))
    result.add_argument("--metis-root", type=Path, default=DEFAULT_METIS_ROOT)
    result.add_argument("--node-path", type=Path, default=DEFAULT_NODE)
    result.add_argument("--remote", default="origin")
    result.add_argument("--reviews", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return {
            "truth": truth,
            "freeze": freeze,
            "run": run,
            "evidence": evidence,
            "adjudicate": adjudicate,
        }[args.mode](args)
    except (
        GrammarStdlibT30Error,
        qlora.RuntimeContractError,
        oracle.GrammarStdlibOracleError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
