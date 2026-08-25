"""Sealed, held-out T30 grammar and Metis-standard-library evaluation.

T30 is deliberately a new evaluator rather than a switch on the historical
D18 runner.  It has its own task roster, truth, freeze, attempt receipt and
evidence.  In particular it is *not* a dataset builder, trainer, optimiser or
promotion path.  The only model interaction is the single sealed base pass and
the single sealed adapter pass performed by :func:`run`.
"""

from __future__ import annotations

import argparse
import json
import os
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
from metis_model1 import initial_local_qlora_runtime as qlora
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
DEFAULT_METIS_ROOT = d18.DEFAULT_METIS_ROOT
DEFAULT_NODE = d18.DEFAULT_NODE
QUALIFICATION_PYTHON = d18.QUALIFICATION_PYTHON
BENCHMARK_ID = "grammar-stdlib-accuracy-t30-v1"
FAMILIES = tuple(f"F-{number}" for number in range(1, 7))
TOP_LEVELS = d18.TOP_LEVELS
STDLIB_MEMBERS = d18.STDLIB_MEMBERS
STDLIB_SETTINGS = d18.STDLIB_SETTINGS
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
# Explicitly includes the T30 implementation so code drift invalidates its seal.
BOUND_PATHS = (
    "fixtures/grammar-stdlib-accuracy-v1/t30-tasks.json",
    "fixtures/grammar-stdlib-accuracy-v1/t30-reference-context.md",
    "manifests/grammar-stdlib-accuracy-t30-policy-v1.json",
    "manifests/grammar-stdlib-accuracy-t30-truth-v1.json",
    "manifests/catalog-maintenance-pin-v1.json",
    "manifests/grammar-stdlib-pin-v1.json",
    "src/metis_model1/grammar_stdlib_t30.py",
    "src/metis_model1/demo_accuracy.py",
    "src/metis_model1/grammar_stdlib_accuracy.py",
    "src/metis_model1/grammar_stdlib_oracle.py",
    "src/metis_model1/grammar_stdlib_coverage.py",
    "src/metis_model1/initial_local_qlora_runtime.py",
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
        "policy_id": "grammar-stdlib-accuracy-t30-policy/v1",
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
    if value.get("roster") != {
        "tasks": 30,
        "tasks_per_family": 5,
        "automatic_tasks": 20,
        "human_review_task_ids_expected": 15,
        "human_review_families": ["F-2", "F-5", "F-6"],
        "top_levels_required": 10,
        "stdlib_members_required": 12,
        "stdlib_settings_required": 1,
        "rare_or_critical_construct_min_occurrences": 2,
        "catalog_domain_family_reservations": ["F-1", "F-6"],
    }:
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
    if value.get("coverage_gate") != {
        "credit_source": "final_successful_tasks_only",
        "declared_metadata_alone_is_ineligible": True,
        "top_levels": "all_10",
        "stdlib_members": "all_12",
        "stdlib_settings": ["time.timezone"],
    }:
        raise GrammarStdlibT30Error("ratified T30 coverage gate drift")
    if value.get("decision_policy") != {
        "pre_review_verdict": "GRAMMAR_STDLIB_T30_REVIEW_REQUIRED",
        "passing_verdict": "GRAMMAR_STDLIB_T30_PASS_NO_RETRAIN",
        "failing_verdict": "GRAMMAR_STDLIB_T30_DIAGNOSE",
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
        "requests_per_worker": 30,
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
        or manifest.get("roster_id") != "gsl_t30_public_synthetic_v1"
        or manifest.get("policy_id") != "grammar-stdlib-accuracy-t30-policy/v1"
        or manifest.get("benchmark_id") != BENCHMARK_ID
    ):
        raise GrammarStdlibT30Error("T30 roster identity differs from fixed contract")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping) or provenance != {
        "kind": "public_synthetic",
        "namespace": "gsl_t30",
        "pin_revision": "5e112f9148f40e7e792052e896c5a9efe8eaf0a2",
        "language_version": "0.43",
        "source_validation": "pinned_oracle_required_before_truth",
        "model_outputs_observed": False,
        "training_input_allowed": False,
        "delta_qlora_input_allowed": False,
    }:
        raise GrammarStdlibT30Error("T30 roster provenance is not pre-output public synthetic")
    rows = manifest.get("tasks")
    if not isinstance(rows, list) or len(rows) != 30:
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
            or not task_id.startswith("gsl_t30_")
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
        coverage, provenance_roots = row.get("coverage"), row.get("provenance_roots")
        if (
            not isinstance(coverage, Mapping)
            or set(coverage) != {"top_levels", "stdlib_members", "stdlib_settings"}
            or not all(isinstance(coverage.get(key), list) for key in coverage)
            or not set(coverage["top_levels"]).issubset(TOP_LEVELS)
            or not set(coverage["stdlib_members"]).issubset(STDLIB_MEMBERS)
            or not set(coverage["stdlib_settings"]).issubset(STDLIB_SETTINGS)
            or not isinstance(provenance_roots, Mapping)
            or set(provenance_roots) != {"independent", "template"}
            or not all(
                isinstance(value, str) and value.startswith("gsl_t30_")
                for value in provenance_roots.values()
            )
            or provenance_roots["independent"] == provenance_roots["template"]
        ):
            raise GrammarStdlibT30Error("T30 coverage or provenance roots are invalid")
        ids.add(task_id)
        roots.add(str(provenance_roots["independent"]))
        templates.add(str(provenance_roots["template"]))
        result.append(dict(row))
    if Counter(item["family"] for item in result) != Counter({family: 5 for family in FAMILIES}):
        raise GrammarStdlibT30Error("T30 family census must be exactly five per family")
    if roots & templates or len(roots) != 30 or len(templates) != 30:
        raise GrammarStdlibT30Error("T30 provenance roots are not globally disjoint")
    if {value for task in result for value in task["coverage"]["top_levels"]} != TOP_LEVELS:
        raise GrammarStdlibT30Error("T30 top-level denominator drift")
    if {value for task in result for value in task["coverage"]["stdlib_members"]} != STDLIB_MEMBERS:
        raise GrammarStdlibT30Error("T30 standard-library member denominator drift")
    if {
        value for task in result for value in task["coverage"]["stdlib_settings"]
    } != STDLIB_SETTINGS:
        raise GrammarStdlibT30Error("T30 standard-library setting denominator drift")
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
    required_markers = {
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
    forbidden_markers = {"gsl_d18", "play-prod", "play-demo", "tenant data", "training example"}
    if (
        not reference.startswith("# Metis 0.43 grammar and standard-library reference\n")
        or any(marker not in reference for marker in required_markers)
        or any(
            marker in reference
            for marker in forbidden_markers - {"tenant data", "training example"}
        )
        or "not tenant data and not a training example" not in reference
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
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate once and retain the pinned AST needed by review/coverage truth."""

    try:
        envelope = d18._oracle_task(task, source, metis_root, node_path, session=session)
        result = envelope["result"]
        if expected_ok:
            if result["status"] != "ok":
                raise GrammarStdlibT30Error(f"expected input rejected by oracle: {task['task_id']}")
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
    result = {
        "top_levels": top_levels,
        "stdlib_members": members,
        "stdlib_settings": list(dict.fromkeys(settings)),
    }
    if (
        not set(result["top_levels"]).issubset(TOP_LEVELS)
        or not set(result["stdlib_members"]).issubset(STDLIB_MEMBERS)
        or not set(result["stdlib_settings"]).issubset(STDLIB_SETTINGS)
    ):
        raise GrammarStdlibT30Error("pinned AST coverage escaped the T30 denominator")
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
    return result


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
            result.append({"name": name, "domain": "external-enum", "size": marker.get("size")})
        elif isinstance(marker, Mapping) and marker.get("$type") == "OpenMarker":
            result.append({"name": name, "domain": "open"})
        else:
            raise GrammarStdlibT30Error("catalog field domain is outside the structural contract")
    return result


def _f4_review_target(task: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    result = envelope["result"]
    coverage = _coverage_from_inventory(result["ast"]["inventory"])
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
    if len(variants) > 1:
        raise GrammarStdlibT30Error("F4 review target has ambiguous variants")
    if variants:
        endpoint["variant"] = variants[0]
    return {
        "contract": d18.SEMANTIC_SIGNATURE_CONTRACT,
        "status": result["status"],
        **coverage,
        "endpoint": endpoint,
    }


def _f6_review_target(task: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    inventory = envelope["result"]["ast"]["inventory"]
    coverage = _coverage_from_inventory(inventory)
    result: dict[str, Any] = {
        "contract": "metis-structural-explanation/v1",
        "top_levels": coverage["top_levels"],
        "declarations": _declarations_from_inventory(inventory),
    }
    if "catalog_fields" in task["expected_json"]:
        result["catalog_fields"] = _catalog_fields(inventory)
    result.update(
        {
            "stdlib_members": coverage["stdlib_members"],
            "stdlib_settings": coverage["stdlib_settings"],
            "relationships": _relationships_from_inventory(inventory),
        }
    )
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
                target["before"] = _validate_source(
                    task,
                    str(task["before_source"]),
                    metis_root,
                    node_path,
                    session,
                    expected_ok=task["oracle"]["input_failure_kind"] is None,
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
                target["repaired"] = _validate_source(
                    task,
                    str(task["expected_repaired_source"]),
                    metis_root,
                    node_path,
                    session,
                    expected_ok=True,
                )
            if task["task_mode"] == "source_output":
                target["expected"], expected_envelope = _validate_source_envelope(
                    task,
                    str(task.get("expected_source", task.get("expected_repaired_source"))),
                    metis_root,
                    node_path,
                    session,
                    expected_ok=True,
                )
                target["expected_coverage"] = _coverage_from_inventory(
                    expected_envelope["result"]["ast"]["inventory"]
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
                target["expected_coverage"] = _coverage_from_inventory(
                    input_envelope["result"]["ast"]["inventory"]
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
        "truth_id": "grammar-stdlib-accuracy-t30-truth/v1",
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
            "tasks_in": 30,
            "tasks_out": 30,
            "tasks_distinct": 30,
            "gaps": 0,
            "families": {family: 5 for family in FAMILIES},
        },
        "tasks": records,
        "model_outputs_observed": False,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "nonclaims": NONCLAIMS,
    }
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


def _runtime_identities() -> dict[str, Any]:
    dataset = qlora._check_receipt(DATASET_RECEIPT_PATH)
    restore = qlora.verify_adapter_off_restore_receipt(
        qlora.DEFAULT_RESTORE_RECEIPT,
        adapter=ADAPTER_PATH,
        dataset_receipt=DATASET_RECEIPT_PATH,
        selection_receipt=qlora.DEFAULT_SELECTION_RECEIPT,
    )
    restore_raw = safe._read_regular(
        qlora.DEFAULT_RESTORE_RECEIPT, "adapter-off restore receipt", 8 * 1024 * 1024
    )
    return {
        "runtime": qlora._check_runtime(),
        "base": qlora.evaluation_identity(qlora.BASE_CHECKPOINT, None),
        "adapter": qlora.evaluation_identity(qlora.BASE_CHECKPOINT, ADAPTER_PATH),
        "dataset": dataset,
        "adapter_off_restore": {
            "path": str(qlora.DEFAULT_RESTORE_RECEIPT.relative_to(PROJECT_ROOT)),
            "bytes": len(restore_raw),
            "sha256": raw_hash(restore_raw),
            "restore_sha256": restore["restore_sha256"],
            "selected_step": restore["selected_step"],
            "adapter_sha256": restore["adapter_sha256"],
            "exact_candidate_restore": restore["exact_candidate_restore"],
        },
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
    d18_ids = {str(row["task_id"]) for row in d18_tasks} | {
        str(row["task_id"]) for row in d18_truth["tasks"]
    }
    if d18_ids & {str(row["task_id"]) for row in tasks}:
        raise GrammarStdlibT30Error("T30 task identifiers overlap D18")
    d18_messages = {d18.canonical_hash(d18.build_messages(row)) for row in d18_tasks}
    messages = {canonical_hash(build_messages(row)) for row in tasks}
    if d18_messages & messages:
        raise GrammarStdlibT30Error("T30 messages overlap D18")
    content_roots = [_task_content_root(row) for row in tasks]
    declared_roots = [item["target"].get("content_root_sha256") for item in truth["tasks"]]
    if any(value is not None for value in declared_roots) and declared_roots != content_roots:
        raise GrammarStdlibT30Error("T30 truth content roots differ from its roster")
    if len(content_roots) != 30 or len(set(content_roots)) != 30:
        raise GrammarStdlibT30Error("T30 content-derived roots are not distinct")
    if set(content_roots) & {_task_content_root(row) for row in d18_tasks}:
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

    if semantic_hashes(truth) & semantic_hashes(d18_truth):
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
        if not isinstance(raw, bytes) or b"gsl_t30" in raw:
            raise GrammarStdlibT30Error("T30 namespace overlaps a historical fixture")
    qlora._check_receipt(DATASET_RECEIPT_PATH)
    for split in ("train.jsonl", "dev.jsonl"):
        raw = safe._read_regular(
            DATASET_RECEIPT_PATH.parent / split,
            f"verified training split {split}",
            64 * 1024 * 1024,
        )
        if b"gsl_t30" in raw:
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
        "freeze_id": "grammar-stdlib-accuracy-t30-freeze/v1",
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
    if (
        set(value) != required
        or value.get("schema_version") != 1
        or value.get("freeze_id") != "grammar-stdlib-accuracy-t30-freeze/v1"
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


def _review_json_contract_failure(task: Mapping[str, Any], value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return "json_contract_mismatch"
    for key, allowed in (
        ("top_levels", TOP_LEVELS),
        ("stdlib_members", STDLIB_MEMBERS),
        ("stdlib_settings", STDLIB_SETTINGS),
    ):
        items = value.get(key)
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            return "json_contract_mismatch"
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
            return "json_contract_mismatch"
        for key in ("requested", "selected", "variant"):
            item = endpoint.get(key)
            if item is not None and item != expected_endpoint.get(key):
                return "invented_symbol"
    return None


def _coverage_from_review_json(value: Mapping[str, Any]) -> dict[str, list[str]]:
    return {
        "top_levels": list(value["top_levels"]),
        "stdlib_members": list(value["stdlib_members"]),
        "stdlib_settings": list(value["stdlib_settings"]),
    }


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
    observed_coverage = {"top_levels": [], "stdlib_members": [], "stdlib_settings": []}
    if task["task_mode"] == "source_output":
        source, failure = _extract_source(text)
        if source is not None:
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
                    observed_coverage = _coverage_from_inventory(
                        envelope["result"]["ast"]["inventory"]
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
            failure = "json_contract_mismatch"
        if isinstance(value, Mapping) and failure not in {
            "invented_symbol",
            "json_contract_mismatch",
        }:
            observed_coverage = _coverage_from_review_json(value)
        observed = None if value is None else {"json": value, "json_sha256": canonical_hash(value)}
    automatic = task["family"] in {"F-1", "F-2", "F-3", "F-4"}
    semantic_correct: bool | None = correct if automatic else None
    if task["task_mode"] == "exact_json_review" and failure not in {
        None,
        "invented_symbol",
        "json_contract_mismatch",
    }:
        failure = "json_format_mismatch"
    elif not correct and failure is None:
        failure = "human_review_mismatch" if not automatic else "semantic_mismatch"
    harmless = {
        None,
        "semantic_mismatch",
        "human_review_mismatch",
        "json_format_mismatch",
        "json_contract_mismatch",
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
    if len(rows) > 30:
        raise GrammarStdlibT30Error("T30 observation roster is oversized")
    return {
        "tasks_in": 30,
        "tasks_out": len(rows),
        "tasks_distinct": len({row["task_id"] for row in rows}),
        "gaps": 30 - len(rows),
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
        len(base) != 30
        or len(adapter) != 30
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
        "complete": right["gaps"] == 0 and right["tasks_distinct"] == 30,
        "no_paired_regression": not regressions and not mechanical_regressions,
    }
    pending = [row["task_id"] for row in adapter if row["final_human_review_required"]]
    return {
        "verdict": "GRAMMAR_STDLIB_T30_REVIEW_REQUIRED"
        if all(gates.values())
        else "GRAMMAR_STDLIB_T30_DIAGNOSE",
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
        "base_requests": 30,
        "adapter_requests": 30,
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
        or value.get("base_requests") != 30
        or value.get("adapter_requests") != 30
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
    if len(tasks) != 30 or len(rows) != 30:
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
    if len(lines) != 30:
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
        "evidence_id": "grammar-stdlib-accuracy-t30-evaluation/v1",
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
        or value.get("review_id") != "grammar-stdlib-accuracy-t30-human-review/v1"
        or value.get("authority_tier") != "human_review_required"
        or value.get("reviewer_role") != "L0_frontier_coordinator"
        or value.get("evaluation_sha256") != evaluation.get("evaluation_sha256")
        or not isinstance(value.get("reviews"), list)
        or len(value["reviews"]) != 15
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


def _final_adjudication(
    evaluation: Mapping[str, Any],
    reviews: Mapping[str, Any],
    freeze_value: Mapping[str, Any],
) -> dict[str, Any]:
    review_by_id = {row["task_id"]: row for row in reviews["reviews"]}
    rows = evaluation["observations"]["adapter"]
    if not isinstance(rows, list) or len(rows) != 30:
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
            or set(coverage) != {"top_levels", "stdlib_members", "stdlib_settings"}
            or not all(isinstance(coverage.get(key), list) for key in coverage)
            or not set(coverage["top_levels"]).issubset(TOP_LEVELS)
            or not set(coverage["stdlib_members"]).issubset(STDLIB_MEMBERS)
            or not set(coverage["stdlib_settings"]).issubset(STDLIB_SETTINGS)
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
    coverage = {
        "top_levels": sorted(
            {value for row in successful for value in row["observed_coverage"]["top_levels"]}
        ),
        "stdlib_members": sorted(
            {value for row in successful for value in row["observed_coverage"]["stdlib_members"]}
        ),
        "stdlib_settings": sorted(
            {value for row in successful for value in row["observed_coverage"]["stdlib_settings"]}
        ),
    }
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
        "human_reviews_complete": len(review_by_id) == 15
        and all(row["decision"] in {"ACCEPT", "REJECT"} for row in reviews["reviews"]),
        "critical_veto_clear": prior["adapter"]["critical_failure"] == 0,
        "no_paired_regression": not prior["paired_regressions"]
        and not prior["paired_mechanical_regressions"],
        "complete": prior["gates"]["complete"],
        "automatic_gate": prior["gates"]["automatic_semantic_total"]
        and prior["gates"]["automatic_semantic_denominator"]
        and prior["gates"]["automatic_family_floor"],
        "coverage_all_10_top_levels": set(coverage["top_levels"]) == TOP_LEVELS,
        "coverage_all_12_stdlib_members": set(coverage["stdlib_members"]) == STDLIB_MEMBERS,
        "coverage_time_timezone": set(coverage["stdlib_settings"]) == STDLIB_SETTINGS,
        "adapter_off_exact_restore": restore.get("exact_candidate_restore") is True,
    }
    verdict = (
        "GRAMMAR_STDLIB_T30_PASS_NO_RETRAIN"
        if all(gates.values())
        else "GRAMMAR_STDLIB_T30_DIAGNOSE"
    )
    return {
        "verdict": verdict,
        "authority_tier": "local_held_out_grammar_stdlib",
        "semantic_correct": len(successful),
        "semantic_denominator": 30,
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
        "adjudication_id": "grammar-stdlib-accuracy-t30-adjudication/v1",
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
