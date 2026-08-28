"""D18 grammar-and-standard-library accuracy gate.

This is a sealed evaluator, not a corpus builder or training entry point.  It
uses :mod:`grammar_stdlib_oracle` for every grammar judgement and keeps model
responses only in the ignored per-run directory.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import stat
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metis_model1 import demo_accuracy as safe
from metis_model1 import grammar_stdlib_oracle as oracle
from metis_model1 import initial_local_qlora_runtime as qlora
from metis_model1.catalog_maintenance_probe import _extract_source

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASKS_PATH = PROJECT_ROOT / "fixtures/grammar-stdlib-accuracy-v1/d18-tasks.json"
REFERENCE_PATH = PROJECT_ROOT / "fixtures/grammar-stdlib-accuracy-v1/reference-context.md"
TRUTH_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-d18-truth-v1.json"
FREEZE_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-d18-freeze-v1.json"
EVIDENCE_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-d18-evaluation-v1.json"
RUN_ROOT = PROJECT_ROOT / "artifacts/grammar-stdlib-accuracy/d18"
ADAPTER_PATH = PROJECT_ROOT / "artifacts/initial-local-qlora-v1/run-v2/checkpoints/step-00000050"
DEFAULT_METIS_ROOT = Path(
    os.environ.get(
        "METIS_MODEL1_METIS_ROOT",
        "/Users/tommasotessarolo/Developer/ares-matioska/metis",
    )
)
DEFAULT_NODE = Path(
    os.environ.get(
        "METIS_MODEL1_NODE",
        "/Users/tommasotessarolo/.nvm/versions/node/v22.22.3/bin/node",
    )
)
QUALIFICATION_PYTHON = PROJECT_ROOT / "qualification/.venv/bin/python"
BENCHMARK_ID = "grammar-stdlib-accuracy-d18-v1"
FAMILIES = tuple(f"F-{item}" for item in range(1, 7))
GENERATION = {"temperature": 0, "seed": 17, "thinking": False, "max_tokens": 512}
THRESHOLDS = {
    "automatic_semantic_total_min": 8,
    "automatic_semantic_denominator": 9,
    "automatic_family_min": 2,
    "critical_max": 0,
    "adapter_regression_allowed": False,
}
TASK_MODES = {"source_output", "exact_json_review"}
TASK_TIERS = {
    "F-1": "pinned_oracle_required",
    "F-2": "pinned_oracle_required",
    "F-3": "pinned_oracle_required",
    "F-4": "diagnostic_only",
    "F-5": "human_review_required",
    "F-6": "human_review_required",
}
TASK_KINDS = {
    "F-1": "author_source",
    "F-2": "repair_source",
    "F-3": "author_source",
    "F-4": "diagnostic_review",
    "F-5": "migration_source",
    "F-6": "structural_review",
}
TOP_LEVELS = {
    "Tenant",
    "Catalog",
    "Property",
    "Endpoint",
    "Preset",
    "List",
    "Transformer",
    "NamedBlock",
    "SettingsDecl",
    "ValueSet",
}
STDLIB_MEMBERS = {
    "time.now",
    "time.month",
    "time.day",
    "time.hour",
    "time.hhmm",
    "time.weekday",
    "time.fractional_second",
    "codec.decode",
    "codec.encode",
    "text.slugify",
    "text.truncate",
    "text.normalize",
}
STDLIB_SETTINGS = {"time.timezone"}
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
NONCLAIMS = [
    "no_training_authority",
    "no_delta_qlora_authority",
    "no_dataset_authority",
    "no_promotion_authority",
    "no_global_accuracy_claim",
    "diagnostic_only",
]
BOUND_PATHS = (
    "fixtures/grammar-stdlib-accuracy-v1/d18-tasks.json",
    "fixtures/grammar-stdlib-accuracy-v1/reference-context.md",
    "manifests/catalog-maintenance-pin-v1.json",
    "manifests/grammar-stdlib-accuracy-d18-truth-v1.json",
    "manifests/grammar-stdlib-pin-v1.json",
    "src/metis_model1/demo_accuracy.py",
    "src/metis_model1/grammar_stdlib_accuracy.py",
    "src/metis_model1/grammar_stdlib_oracle.py",
    "src/metis_model1/grammar_stdlib_coverage.py",
    "src/metis_model1/initial_local_qlora_runtime.py",
    "src/metis_model1/catalog_maintenance_probe.py",
    "src/metis_model1/catalog_maintenance_pin.py",
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


class GrammarStdlibAccuracyError(RuntimeError):
    """The D18 pre-output or evidence contract was not met."""


def canonical_hash(value: Any) -> str:
    return safe.canonical_hash(value)


def raw_hash(value: bytes) -> str:
    return safe.raw_hash(value)


def _load(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    raw = safe._read_regular(path, label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GrammarStdlibAccuracyError(f"{label} is not JSON") from error
    if not isinstance(value, dict):
        raise GrammarStdlibAccuracyError(f"{label} must be an object")
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
        "training_label_eligible",
    }
    if "input_source" in task:
        keys.add("input_source")
    if "before_source" in task:
        keys.add("before_source")
    if "expected_repaired_source" in task:
        keys.add("expected_repaired_source")
    keys.add("expected_source" if task.get("task_mode") == "source_output" else "expected_json")
    return keys


def validate_tasks(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    expected = {"schema_version", "roster_id", "provenance", "tasks"}
    if (
        set(manifest) != expected
        or manifest.get("schema_version") != 2
        or manifest.get("roster_id") != "gsl_d18_public_synthetic_v2"
    ):
        raise GrammarStdlibAccuracyError("D18 roster header differs from the fixed contract")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict) or provenance != {
        "kind": "public_synthetic",
        "namespace": "gsl_d18",
        "pin_revision": "5e112f9148f40e7e792052e896c5a9efe8eaf0a2",
        "language_version": "0.43",
        "source_validation": "pinned_oracle_required_before_truth",
        "model_outputs_observed": False,
        "training_input_allowed": False,
    }:
        raise GrammarStdlibAccuracyError("D18 roster provenance is not pre-output public synthetic")
    rows = manifest.get("tasks")
    if not isinstance(rows, list) or len(rows) != 18:
        raise GrammarStdlibAccuracyError("D18 roster must contain exactly eighteen tasks")
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != _task_keys(row):
            raise GrammarStdlibAccuracyError("D18 task fields differ from the fixed contract")
        task_id, family, mode = row.get("task_id"), row.get("family"), row.get("task_mode")
        if (
            not isinstance(task_id, str)
            or not task_id.startswith("gsl_d18_")
            or task_id in seen
            or family not in FAMILIES
            or mode not in TASK_MODES
            or row.get("kind") != TASK_KINDS.get(family)
            or row.get("authority_tier") != TASK_TIERS.get(family)
        ):
            raise GrammarStdlibAccuracyError("D18 task identity or family is invalid")
        if (
            not isinstance(row.get("prompt"), str)
            or not row["prompt"]
            or row.get("model_outputs_observed") is not False
            or row.get("training_input_allowed") is not False
            or row.get("training_label_eligible") is not False
        ):
            raise GrammarStdlibAccuracyError("D18 task is not a pre-output prompt")
        spec = row.get("oracle")
        if not isinstance(spec, dict):
            raise GrammarStdlibAccuracyError("D18 oracle specification is invalid")
        expected_oracle_keys = {
            "mode",
            "input_status",
            "input_failure_kind",
            "diagnostic_substrings",
        }
        if spec.get("mode") == "endpoint":
            expected_oracle_keys.add("target")
        if "expected_diagnostic_substrings" in spec:
            expected_oracle_keys.add("expected_diagnostic_substrings")
        if (
            set(spec) != expected_oracle_keys
            or spec.get("mode") not in {"source", "endpoint"}
            or spec.get("input_status") != "pinned_oracle_required_before_truth"
            or spec.get("input_failure_kind") not in {None, "parser", "link", "validation"}
            or not isinstance(spec.get("diagnostic_substrings"), list)
            or not all(isinstance(item, str) and item for item in spec["diagnostic_substrings"])
            or (
                "expected_diagnostic_substrings" in spec
                and (
                    mode != "source_output"
                    or not isinstance(spec["expected_diagnostic_substrings"], list)
                    or not spec["expected_diagnostic_substrings"]
                    or not all(
                        isinstance(item, str) and item
                        for item in spec["expected_diagnostic_substrings"]
                    )
                )
            )
            or (spec["mode"] == "endpoint" and not isinstance(spec.get("target"), str))
            or (spec["mode"] == "endpoint" and not spec["target"])
            or (spec["input_failure_kind"] is None and spec["diagnostic_substrings"])
            or (spec["input_failure_kind"] is not None and not spec["diagnostic_substrings"])
        ):
            raise GrammarStdlibAccuracyError("D18 oracle specification is invalid")
        if mode == "source_output":
            if not isinstance(row.get("expected_source"), str) or not row["expected_source"]:
                raise GrammarStdlibAccuracyError("D18 source target is invalid")
        elif not isinstance(row.get("expected_json"), dict) or not row["expected_json"]:
            raise GrammarStdlibAccuracyError("D18 JSON target is invalid")
        for field in (
            "input_source",
            "before_source",
            "expected_source",
            "expected_repaired_source",
        ):
            if field in row and (
                not isinstance(row[field], str)
                or not row[field]
                or not row[field].startswith("metis 0.43\n")
            ):
                raise GrammarStdlibAccuracyError(f"D18 {field} is invalid")
        if "before_source" in row and spec["input_failure_kind"] is None:
            raise GrammarStdlibAccuracyError("D18 diagnostic predicates are invalid")
        if "before_source" not in row and spec["input_failure_kind"] is not None:
            raise GrammarStdlibAccuracyError("D18 failure kind has no invalid input")
        coverage = row.get("coverage")
        roots = row.get("provenance_roots")
        if (
            not isinstance(coverage, dict)
            or set(coverage) != {"top_levels", "stdlib_members", "stdlib_settings"}
            or not all(isinstance(coverage.get(k), list) for k in coverage)
            or not set(coverage["top_levels"]).issubset(TOP_LEVELS)
            or not set(coverage["stdlib_members"]).issubset(STDLIB_MEMBERS)
            or not set(coverage["stdlib_settings"]).issubset(STDLIB_SETTINGS)
            or not isinstance(roots, dict)
            or set(roots) != {"independent", "template"}
            or not all(isinstance(v, str) and v.startswith("gsl_d18_") for v in roots.values())
            or roots["independent"] == roots["template"]
        ):
            raise GrammarStdlibAccuracyError("D18 coverage or provenance roots are invalid")
        seen.add(task_id)
        tasks.append(dict(row))
    if Counter(row["family"] for row in tasks) != Counter({family: 3 for family in FAMILIES}):
        raise GrammarStdlibAccuracyError("D18 family census must be exactly three per family")
    if Counter(row["task_mode"] for row in tasks) != Counter(
        {"source_output": 12, "exact_json_review": 6}
    ):
        raise GrammarStdlibAccuracyError(
            "D18 task-mode census must be twelve source and six JSON reviews"
        )
    top_levels = {item for task in tasks for item in task["coverage"]["top_levels"]}
    members = {item for task in tasks for item in task["coverage"]["stdlib_members"]}
    settings = {item for task in tasks for item in task["coverage"]["stdlib_settings"]}
    if top_levels != TOP_LEVELS or members != STDLIB_MEMBERS or settings != STDLIB_SETTINGS:
        raise GrammarStdlibAccuracyError("D18 declared grammar/stdlib denominator drift")
    independent = [task["provenance_roots"]["independent"] for task in tasks]
    templates = [task["provenance_roots"]["template"] for task in tasks]
    if (
        len(independent) != len(set(independent))
        or len(templates) != len(set(templates))
        or set(independent) & set(templates)
    ):
        raise GrammarStdlibAccuracyError("D18 provenance roots are not globally disjoint")
    return tasks


def load_tasks() -> tuple[dict[str, Any], list[dict[str, Any]], bytes]:
    manifest, raw = _load(TASKS_PATH, "D18 tasks")
    return manifest, validate_tasks(manifest), raw


def _reference_context() -> tuple[str, bytes]:
    raw = safe._read_regular(REFERENCE_PATH, "grammar/stdlib reference context", 64 * 1024)
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GrammarStdlibAccuracyError("grammar/stdlib reference context is not UTF-8") from error
    if (
        not value.startswith("# Metis 0.43 grammar and standard-library reference\n")
        or "gsl_d18" in value
        or "play-prod" in value
        or "play-demo" in value
        or "time.fractional_second" not in value
        or "std.codec.decode" not in value
        or "std.text.normalize" not in value
    ):
        raise GrammarStdlibAccuracyError("grammar/stdlib reference context drift")
    return value, raw


def build_messages(task: Mapping[str, Any]) -> list[dict[str, str]]:
    reference, _raw = _reference_context()
    text = str(task["prompt"])
    source = task.get("input_source", task.get("before_source"))
    if source is not None:
        text += "\n\nCurrent Metis source:\n" + str(source).rstrip()
    system = (
        "Return exactly one complete Metis 0.43 source, with no prose."
        if task["task_mode"] == "source_output"
        else "Return exactly one JSON object, with no prose or markdown."
    )
    system += "\n\nRetrieved pinned reference:\n" + reference.rstrip()
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


def _diagnostic_text(envelope: Mapping[str, Any]) -> list[str]:
    all_items = envelope["result"]["diagnostics"]["all"]
    return [
        json.dumps(item, ensure_ascii=False, sort_keys=True) if not isinstance(item, str) else item
        for item in all_items
    ]


def _oracle_task(
    task: Mapping[str, Any],
    source: str,
    metis_root: Path,
    node_path: Path,
    *,
    session: oracle.GrammarStdlibOracleSession | None = None,
) -> dict[str, Any]:
    spec = task["oracle"]
    assert isinstance(spec, Mapping)
    mode = str(spec["mode"])
    arguments = {
        "source": source,
        "filename": f"d18/{task['task_id']}.metis",
        "execution_mode": mode,
        "endpoint": None if mode == "source" else str(spec["target"]),
    }
    if session is not None:
        return session.run(**arguments)
    return oracle.run_grammar_stdlib_oracle(
        metis_root=metis_root,
        node_path=node_path,
        **arguments,
    )


SEMANTIC_SIGNATURE_CONTRACT = "metis-semantic-signature/v2"
_SEMANTIC_AST_DOLLAR_KEYS = {"$type"}
_NONSEMANTIC_AST_KEYS = {
    "$container",
    "$containerIndex",
    "$containerProperty",
    "$cstNode",
    "$document",
    "$refNode",
    "ref",
}
_NONSEMANTIC_AST_PRIVATE_KEYS = {
    "_astNode",
    "_formatted",
    "_fsPath",
    "_hidden",
    "_length",
    "_nodeDescription",
    "_offset",
    "_range",
    "_rangeCache",
    "_ref",
    "_text",
    "_tokenType",
}


def _semantic_hash(kind: str, value: Any) -> str:
    return canonical_hash({"contract": SEMANTIC_SIGNATURE_CONTRACT, "kind": kind, "value": value})


def _reference_identity(value: Mapping[str, Any]) -> dict[str, str]:
    text = value.get("$refText")
    if not isinstance(text, str) or not text:
        raise GrammarStdlibAccuracyError("oracle AST reference text is invalid")
    target = value.get("_ref")
    target_type = target.get("$type") if isinstance(target, Mapping) else None
    target_name = target.get("name") if isinstance(target, Mapping) else None
    description = value.get("_nodeDescription")
    if not isinstance(target_type, str) and isinstance(description, Mapping):
        target_type = description.get("type")
    if not isinstance(target_name, str) and isinstance(description, Mapping):
        target_name = description.get("name")
    if (
        isinstance(target_type, str)
        and target_type
        and isinstance(target_name, str)
        and target_name
    ):
        return {"target_type": target_type, "target_name": target_name}
    return {"unresolved_text": text}


def _semantic_ast(value: Any) -> Any:
    """Remove Langium ownership, CST, cache, and resolved-object metadata."""

    if isinstance(value, list):
        return [_semantic_ast(item) for item in value]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        if "$refText" in value:
            result["$reference"] = _reference_identity(value)
        for key, item in value.items():
            if not isinstance(key, str):
                raise GrammarStdlibAccuracyError("oracle AST contains a non-string key")
            if key == "$refText" or key in _NONSEMANTIC_AST_KEYS:
                continue
            if key.startswith("_"):
                if key not in _NONSEMANTIC_AST_PRIVATE_KEYS:
                    raise GrammarStdlibAccuracyError("oracle AST private metadata drifted")
                continue
            if key.startswith("$") and key not in _SEMANTIC_AST_DOLLAR_KEYS:
                raise GrammarStdlibAccuracyError("oracle AST dollar metadata drifted")
            result[key] = _semantic_ast(item)
        return result
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise GrammarStdlibAccuracyError("oracle AST contains a non-JSON value")


def _semantic_ir(value: Any, *, parent_key: str | None = None) -> Any:
    """Remove only source-location provenance from the pinned canonical IR."""

    if isinstance(value, list):
        return [_semantic_ir(item) for item in value]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise GrammarStdlibAccuracyError("oracle IR contains a non-string key")
            if parent_key == "provenance" and key in {"file", "line"}:
                continue
            result[key] = _semantic_ir(item, parent_key=key)
        return result
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise GrammarStdlibAccuracyError("oracle IR contains a non-JSON value")


def _semantic_diagnostics(value: Any) -> dict[str, list[dict[str, Any]]]:
    """Retain diagnostic meaning while excluding source ranges."""

    categories = ("parser", "link", "validation", "all")
    if not isinstance(value, Mapping) or set(value) != set(categories):
        raise GrammarStdlibAccuracyError("oracle diagnostic categories drifted")
    result: dict[str, list[dict[str, Any]]] = {}
    for category in categories:
        rows = value[category]
        if not isinstance(rows, list):
            raise GrammarStdlibAccuracyError("oracle diagnostic category is not a list")
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != {
                "filename",
                "message",
                "severity",
                "code",
                "range",
            }:
                raise GrammarStdlibAccuracyError("oracle diagnostic fields drifted")
            if not isinstance(row["filename"], str) or not isinstance(row["message"], str):
                raise GrammarStdlibAccuracyError("oracle diagnostic identity is invalid")
            normalized.append(
                {
                    "code": row["code"],
                    "filename": row["filename"],
                    "message": row["message"],
                    "severity": row["severity"],
                }
            )
        result[category] = sorted(normalized, key=safe.canonical_bytes)
    if Counter(map(safe.canonical_bytes, result["all"])) != Counter(
        map(safe.canonical_bytes, [*result["link"], *result["validation"]])
    ):
        raise GrammarStdlibAccuracyError("oracle diagnostic phase partition drifted")
    return result


def _oracle_signature(envelope: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    result = envelope["result"]
    mode = str(task["oracle"]["mode"])
    requested = None if mode == "source" else str(task["oracle"]["target"])
    endpoint = result["endpoint"]
    if result["status"] == "ok" and mode == "endpoint" and endpoint.get("name") != requested:
        raise GrammarStdlibAccuracyError("oracle selected a different endpoint")
    ir_value = result["ir"]["value"]
    failure = result["failure"]
    return {
        "contract": SEMANTIC_SIGNATURE_CONTRACT,
        "status": result["status"],
        "endpoint": {
            "mode": mode,
            "requested": requested,
            "selected": endpoint["name"],
            "count": endpoint["count"],
        },
        "semantic_ast_sha256": _semantic_hash("ast", _semantic_ast(result["ast"]["inventory"])),
        "semantic_ir_sha256": (
            None if ir_value is None else _semantic_hash("ir", _semantic_ir(ir_value))
        ),
        "semantic_diagnostics_sha256": _semantic_hash(
            "diagnostics", _semantic_diagnostics(result["diagnostics"])
        ),
        "failure_kind": None if failure is None else failure.get("kind"),
    }


def _validate_oracle_input(
    task: Mapping[str, Any],
    source: str,
    metis_root: Path,
    node_path: Path,
    *,
    expected_ok: bool,
    expected_diagnostic_markers: list[str] | None = None,
    session: oracle.GrammarStdlibOracleSession | None = None,
) -> dict[str, Any]:
    """Run and bind one task input without translating Metis diagnostics."""

    envelope = _oracle_task(task, source, metis_root, node_path, session=session)
    result = envelope["result"]
    expected_kind = task["oracle"]["input_failure_kind"]
    if expected_ok:
        if result["status"] != "ok":
            raise GrammarStdlibAccuracyError(
                f"expected input rejected by oracle: {task['task_id']}"
            )
        diagnostics = _diagnostic_text(envelope)
        missing = [
            marker
            for marker in expected_diagnostic_markers or []
            if not any(marker in text for text in diagnostics)
        ]
        if missing:
            raise GrammarStdlibAccuracyError(
                "expected diagnostic predicate has no actual oracle match for "
                f"{task['task_id']}: {missing[0]}"
            )
    else:
        if result["status"] != "invalid":
            raise GrammarStdlibAccuracyError(f"invalid input accepted by oracle: {task['task_id']}")
        diagnostics = _diagnostic_text(envelope)
        missing = [
            marker
            for marker in task["oracle"]["diagnostic_substrings"]
            if not any(marker in text for text in diagnostics)
        ]
        if missing:
            raise GrammarStdlibAccuracyError(
                "diagnostic predicate has no actual oracle match for "
                f"{task['task_id']}: {missing[0]}"
            )
        if not isinstance(expected_kind, str) or not result["diagnostics"].get(expected_kind):
            raise GrammarStdlibAccuracyError(
                f"oracle failure kind mismatch for {task['task_id']}: {expected_kind}"
            )
    return _oracle_signature(envelope, task)


def build_truth(metis_root: Path, node_path: Path) -> dict[str, Any]:
    _manifest, tasks, raw = load_tasks()
    _reference, reference_raw = _reference_context()
    records: list[dict[str, Any]] = []
    with oracle.grammar_stdlib_oracle_session(
        metis_root=metis_root, node_path=node_path
    ) as oracle_session:
        pin = dict(oracle_session.pin_identity)
        for task in tasks:
            expected_source = task.get("expected_source")
            expected_oracle = None
            if expected_source is not None:
                expected_oracle = _validate_oracle_input(
                    task,
                    str(expected_source),
                    metis_root,
                    node_path,
                    expected_ok=True,
                    expected_diagnostic_markers=list(
                        task["oracle"].get("expected_diagnostic_substrings", [])
                    ),
                    session=oracle_session,
                )
            before = task.get("before_source")
            before_signature = None
            if before is not None:
                before_signature = _validate_oracle_input(
                    task,
                    str(before),
                    metis_root,
                    node_path,
                    expected_ok=False,
                    session=oracle_session,
                )
            input_signature = None
            if task.get("input_source") is not None:
                input_signature = _validate_oracle_input(
                    task,
                    str(task["input_source"]),
                    metis_root,
                    node_path,
                    expected_ok=True,
                    session=oracle_session,
                )
            repaired_signature = None
            if task.get("expected_repaired_source") is not None:
                repaired_signature = _validate_oracle_input(
                    task,
                    str(task["expected_repaired_source"]),
                    metis_root,
                    node_path,
                    expected_ok=True,
                    session=oracle_session,
                )
            target: dict[str, Any] = {
                "kind": task["task_mode"],
                "authority_tier": task["authority_tier"],
                "messages_sha256": canonical_hash(build_messages(task)),
                "before": before_signature,
                "input": input_signature,
                "repaired": repaired_signature,
                "declared_coverage": task["coverage"],
            }
            if expected_oracle is not None:
                target["expected"] = expected_oracle
            else:
                target["expected_json_sha256"] = canonical_hash(task["expected_json"])
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
        "truth_id": "grammar-stdlib-accuracy-d18-truth/v1",
        "status": "truth_fixed_before_model_output",
        "authority_tier": "automatic",
        "benchmark_id": BENCHMARK_ID,
        "semantic_signature_contract": SEMANTIC_SIGNATURE_CONTRACT,
        "tasks_file_sha256": raw_hash(raw),
        "reference_context_sha256": raw_hash(reference_raw),
        "grammar_stdlib_pin": pin,
        "generation": GENERATION,
        "thresholds": THRESHOLDS,
        "counts": {
            "tasks_in": 18,
            "tasks_out": 18,
            "tasks_distinct": 18,
            "gaps": 0,
            "families": {item: 3 for item in FAMILIES},
        },
        "tasks": records,
        "model_outputs_observed": False,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "nonclaims": NONCLAIMS,
    }
    body["truth_sha256"] = canonical_hash(body)
    return body


def truth(args: argparse.Namespace) -> int:
    if TRUTH_PATH.exists() or TRUTH_PATH.is_symlink():
        raise GrammarStdlibAccuracyError("truth output already exists")
    body = build_truth(Path(args.metis_root), Path(args.node_path))
    safe._atomic_json(TRUTH_PATH, body)
    print(
        json.dumps(
            {"event": "grammar_stdlib_d18_truth", "truth_sha256": body["truth_sha256"]},
            sort_keys=True,
        )
    )
    return 0


def _run_dir(run_id: str) -> Path:
    if not RUN_ID_RE.fullmatch(run_id):
        raise GrammarStdlibAccuracyError("run_id must be a bounded lowercase identifier")
    return RUN_ROOT / run_id


def _self_hash(value: Mapping[str, Any], field: str) -> None:
    if value.get(field) != canonical_hash(
        {key: item for key, item in value.items() if key != field}
    ):
        raise GrammarStdlibAccuracyError(f"{field} does not match canonical body")


def _runtime_identities() -> dict[str, Any]:
    return {
        "runtime": qlora._check_runtime(),
        "base": qlora.evaluation_identity(qlora.BASE_CHECKPOINT, None),
        "adapter": qlora.evaluation_identity(qlora.BASE_CHECKPOINT, ADAPTER_PATH),
    }


def _published(remote: str) -> tuple[str, str, str]:
    if safe._git("status", "--porcelain", "--untracked-files=all"):
        raise GrammarStdlibAccuracyError("clean worktree is required")
    remote_ref = safe._remote_ref(remote)
    head, tree = safe._require_published(remote, remote_ref)
    return head, tree, remote_ref


def build_freeze(remote: str, run_id: str, metis_root: Path, node_path: Path) -> dict[str, Any]:
    head, tree, remote_ref = _published(remote)
    run_dir = _run_dir(run_id)
    if run_dir.exists() or run_dir.is_symlink():
        raise GrammarStdlibAccuracyError("run directory already exists")
    if (
        subprocess.run(
            [
                "/usr/bin/git",
                "-C",
                str(PROJECT_ROOT),
                "check-ignore",
                "-q",
                str(run_dir.relative_to(PROJECT_ROOT)),
            ],
            check=False,
        ).returncode
        != 0
    ):
        raise GrammarStdlibAccuracyError("run directory is not ignored")
    value, raw = _load(TRUTH_PATH, "D18 truth")
    _self_hash(value, "truth_sha256")
    rebuilt = build_truth(metis_root, node_path)
    if value != rebuilt:
        raise GrammarStdlibAccuracyError("truth differs from fresh oracle reconstruction")
    _, _tasks, task_raw = load_tasks()
    _reference, reference_raw = _reference_context()
    if value.get("tasks_file_sha256") != raw_hash(task_raw):
        raise GrammarStdlibAccuracyError("truth does not bind task file")
    bound = [safe._tracked_record(path) for path in BOUND_PATHS]
    body: dict[str, Any] = {
        "schema_version": 1,
        "freeze_id": "grammar-stdlib-accuracy-d18-freeze/v1",
        "status": "frozen_before_model_output",
        "authority_tier": "automatic",
        "preimage_commit": head,
        "preimage_tree": tree,
        "remote": remote,
        "remote_ref": remote_ref,
        "run_id": run_id,
        "run_dir": str(run_dir.relative_to(PROJECT_ROOT)),
        "bound_inputs": bound,
        "truth_sha256": value["truth_sha256"],
        "tasks_file_sha256": raw_hash(task_raw),
        "reference_context_sha256": raw_hash(reference_raw),
        "semantic_signature_contract": SEMANTIC_SIGNATURE_CONTRACT,
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
        raise GrammarStdlibAccuracyError("freeze output already exists")
    body = build_freeze(args.remote, args.run_id, Path(args.metis_root), Path(args.node_path))
    safe._atomic_json(FREEZE_PATH, body)
    print(
        json.dumps(
            {"event": "grammar_stdlib_d18_freeze", "freeze_sha256": body["freeze_sha256"]},
            sort_keys=True,
        )
    )
    return 0


def _verify_bound(records: list[Mapping[str, Any]]) -> None:
    if [record.get("path") for record in records] != list(BOUND_PATHS):
        raise GrammarStdlibAccuracyError("bound input roster drift")
    for record in records:
        if safe._tracked_record(str(record["path"])) != record:
            raise GrammarStdlibAccuracyError(f"bound input changed: {record['path']}")


def _verify_freeze(value: Mapping[str, Any], head: str) -> Path:
    _self_hash(value, "freeze_sha256")
    if (
        value.get("status") != "frozen_before_model_output"
        or value.get("authority_tier") != "automatic"
        or value.get("generation") != GENERATION
        or value.get("thresholds") != THRESHOLDS
        or value.get("semantic_signature_contract") != SEMANTIC_SIGNATURE_CONTRACT
        or value.get("training_authorized") is not False
        or value.get("delta_qlora_authorized") is not False
    ):
        raise GrammarStdlibAccuracyError("freeze is not a D18 pre-output seal")
    run_dir = _run_dir(str(value.get("run_id")))
    if value.get("run_dir") != str(run_dir.relative_to(PROJECT_ROOT)):
        raise GrammarStdlibAccuracyError("freeze run directory drift")
    if safe._git("rev-parse", f"{value.get('preimage_commit')}^{{tree}}") != value.get(
        "preimage_tree"
    ):
        raise GrammarStdlibAccuracyError("freeze preimage tree drift")
    if (
        subprocess.run(
            [
                "/usr/bin/git",
                "-C",
                str(PROJECT_ROOT),
                "merge-base",
                "--is-ancestor",
                str(value["preimage_commit"]),
                head,
            ],
            check=False,
        ).returncode
        != 0
    ):
        raise GrammarStdlibAccuracyError("freeze preimage is not an ancestor")
    _verify_bound(list(value.get("bound_inputs", [])))
    return run_dir


def _verify_frozen_inputs(
    freeze_value: Mapping[str, Any], metis_root: Path, node_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any], bytes]:
    """Rebuild public truth and reject any post-seal task, oracle, or runtime drift."""

    _manifest, tasks, task_raw = load_tasks()
    _reference, reference_raw = _reference_context()
    truth_value, _truth_raw = _load(TRUTH_PATH, "D18 truth")
    _self_hash(truth_value, "truth_sha256")
    if (
        truth_value != build_truth(metis_root, node_path)
        or truth_value.get("truth_sha256") != freeze_value.get("truth_sha256")
        or raw_hash(task_raw) != freeze_value.get("tasks_file_sha256")
        or raw_hash(reference_raw) != freeze_value.get("reference_context_sha256")
        or _runtime_identities() != freeze_value.get("runtime_identities")
    ):
        raise GrammarStdlibAccuracyError("frozen D18 inputs drifted")
    return tasks, truth_value, task_raw


def _extract_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    return safe._extract_json(text)


def score_candidate(
    task: Mapping[str, Any],
    response: Mapping[str, Any],
    truth_task: Mapping[str, Any],
    metis_root: Path,
    node_path: Path,
) -> dict[str, Any]:
    text = response.get("text")
    if not isinstance(text, str) or not text:
        raise GrammarStdlibAccuracyError("empty worker candidate")
    failure: str | None = None
    observed: dict[str, Any] | None = None
    if task["task_mode"] == "source_output":
        source, failure = _extract_source(text)
        if source is not None:
            try:
                observed = _oracle_signature(
                    _oracle_task(task, source, metis_root, node_path), task
                )
            except Exception:  # candidate is redacted into one stable failure category
                failure = "grammar_stdlib_oracle_rejected_candidate"
        correct = failure is None and observed == truth_task["target"].get("expected")
    else:
        value, failure = _extract_json(text)
        expected_json = task["expected_json"]
        expected_hash = canonical_hash(expected_json)
        if expected_hash != truth_task["target"].get("expected_json_sha256"):
            raise GrammarStdlibAccuracyError("D18 JSON target differs from sealed truth")
        correct = failure is None and value is not None and canonical_hash(value) == expected_hash
        observed = None if value is None else {"json_sha256": canonical_hash(value)}
    authority = task["authority_tier"]
    human_review = authority == "human_review_required"
    automatic_semantics = authority == "pinned_oracle_required"
    semantic_correct: bool | None = correct if automatic_semantics else None
    if task["task_mode"] == "exact_json_review":
        if failure is not None:
            failure = "json_format_mismatch"
        elif not correct:
            failure = "human_review_mismatch" if human_review else "diagnostic_review_mismatch"
    elif not correct and failure is None:
        failure = "human_review_mismatch" if human_review else "semantic_mismatch"
    return {
        "task_id": task["task_id"],
        "family": task["family"],
        "task_mode": task["task_mode"],
        "authority_tier": task["authority_tier"],
        "independent_root": task["provenance_roots"]["independent"],
        "mechanical_match": correct,
        "semantic_correct": semantic_correct,
        "critical_failure": failure
        not in {
            None,
            "semantic_mismatch",
            "human_review_mismatch",
            "diagnostic_review_mismatch",
            "json_format_mismatch",
        },
        "failure_code": failure,
        "candidate_sha256": raw_hash(text.encode()),
        "observed": observed,
        "peak_metal_gb": response["peak_metal_gb"],
    }


def summarize(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    automatic_families = tuple(
        family for family in FAMILIES if TASK_TIERS[family] == "pinned_oracle_required"
    )
    return {
        "tasks_in": 18,
        "tasks_out": len(rows),
        "tasks_distinct": len({row["task_id"] for row in rows}),
        "gaps": 18 - len(rows),
        "mechanical_match": sum(bool(row["mechanical_match"]) for row in rows),
        "automatic_semantic_correct": sum(row["semantic_correct"] is True for row in rows),
        "automatic_semantic_denominator": sum(row["semantic_correct"] is not None for row in rows),
        "human_review_pending": sum(
            row["authority_tier"] == "human_review_required" for row in rows
        ),
        "diagnostic_only": sum(row["authority_tier"] == "diagnostic_only" for row in rows),
        "nonautomatic_denominator": sum(row["semantic_correct"] is None for row in rows),
        "critical_failure": sum(bool(row["critical_failure"]) for row in rows),
        "family_mechanical": {
            family: sum(bool(row["mechanical_match"]) for row in rows if row["family"] == family)
            for family in FAMILIES
        },
        "automatic_family_semantic": {
            family: {
                "correct": sum(
                    row["semantic_correct"] is True for row in rows if row["family"] == family
                ),
                "denominator": sum(
                    row["semantic_correct"] is not None for row in rows if row["family"] == family
                ),
            }
            for family in automatic_families
        },
    }


def gate_arithmetic(
    base: list[Mapping[str, Any]], adapter: list[Mapping[str, Any]]
) -> dict[str, Any]:
    if (
        len(base) != 18
        or len(adapter) != 18
        or [item["task_id"] for item in base] != [item["task_id"] for item in adapter]
    ):
        raise GrammarStdlibAccuracyError("paired D18 roster differs")
    left, right = summarize(base), summarize(adapter)
    regressions = [
        a["task_id"]
        for a, b in zip(base, adapter, strict=True)
        if a["semantic_correct"] is True and b["semantic_correct"] is False
    ]
    gates = {
        "automatic_semantic_denominator": right["automatic_semantic_denominator"]
        == THRESHOLDS["automatic_semantic_denominator"],
        "adapter_automatic_semantic_total": right["automatic_semantic_correct"]
        >= THRESHOLDS["automatic_semantic_total_min"],
        "automatic_semantic_family_floor": all(
            counts["denominator"] == 3 and counts["correct"] >= THRESHOLDS["automatic_family_min"]
            for counts in right["automatic_family_semantic"].values()
        ),
        "critical_zero": right["critical_failure"] <= THRESHOLDS["critical_max"],
        "complete": right["gaps"] == 0 and right["tasks_distinct"] == 18,
        "no_paired_regression": not regressions,
    }
    review_required_ids = [
        row["task_id"] for row in adapter if row["authority_tier"] == "human_review_required"
    ]
    genuine = [
        row
        for row in adapter
        if row["failure_code"] == "semantic_mismatch"
        and row["authority_tier"] == "pinned_oracle_required"
    ]
    delta_families = sorted({str(row["family"]) for row in genuine})
    distinct_roots = {str(row["independent_root"]) for row in genuine}
    delta_threshold_met = (
        len(genuine) >= 3 and len(delta_families) >= 2 and len(distinct_roots) == len(genuine)
    )
    return {
        "verdict": (
            "GRAMMAR_STDLIB_D18_REVIEW_REQUIRED"
            if all(gates.values())
            else "GRAMMAR_STDLIB_D18_DIAGNOSE"
        ),
        "authority_tier": "diagnostic_only",
        "base": left,
        "adapter": right,
        "gates": gates,
        "paired_regressions": regressions,
        "review_required": {
            "authority_tier": "human_review_required",
            "task_ids": review_required_ids,
            "automatic_delta_eligible": False,
        },
        "delta_qlora": {
            "threshold_met": delta_threshold_met,
            "authorized": False,
            "authority_tier": "human_review_required",
            "action": "l0_adjudication_required" if delta_threshold_met else "no_automatic_delta",
        },
        "training_authorized": False,
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


def _candidates(tasks: list[Mapping[str, Any]], responses: list[Mapping[str, Any]]) -> bytes:
    return b"".join(
        safe.canonical_bytes(
            {
                "task_id": task["task_id"],
                "text": response["text"],
                "peak_metal_gb": response["peak_metal_gb"],
            }
        )
        + b"\n"
        for task, response in zip(tasks, responses, strict=True)
    )


def _read_candidates(path: Path, tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    raw = safe._read_regular(path, "D18 raw candidates", 32 * 1024 * 1024)
    lines = raw.splitlines()
    if len(lines) != 18:
        raise GrammarStdlibAccuracyError("D18 raw candidate count differs")
    rows: list[dict[str, Any]] = []
    for task, line in zip(tasks, lines, strict=True):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise GrammarStdlibAccuracyError("D18 candidate row is invalid JSON") from error
        if (
            not isinstance(value, dict)
            or set(value) != {"task_id", "text", "peak_metal_gb"}
            or value.get("task_id") != task["task_id"]
            or not isinstance(value.get("text"), str)
            or not value["text"]
            or type(value.get("peak_metal_gb")) not in (int, float)
            or not 0 <= float(value["peak_metal_gb"]) <= qlora.LIMITS["metal_gb"]
            or line != safe.canonical_bytes(value)
        ):
            raise GrammarStdlibAccuracyError("D18 candidate row contract drift")
        rows.append(
            {
                "request_id": task["task_id"],
                "text": value["text"],
                "peak_metal_gb": value["peak_metal_gb"],
            }
        )
    return rows


def _directory_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode)


def _open_direct_directory(path: Path, label: str) -> tuple[int, tuple[int, int, int]]:
    """Open a stable directory without following a path replacement."""

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
        raise GrammarStdlibAccuracyError(f"{label} is unavailable") from error
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISDIR(before.st_mode)
        or not stat.S_ISDIR(opened.st_mode)
        or _directory_identity(before) != _directory_identity(opened)
    ):
        os.close(descriptor)
        raise GrammarStdlibAccuracyError(f"{label} is not a stable direct directory")
    return descriptor, _directory_identity(opened)


def _assert_direct_directory(path: Path, label: str) -> None:
    descriptor, _identity = _open_direct_directory(path, label)
    os.close(descriptor)


def _create_direct_directory(path: Path, label: str) -> None:
    """Create exactly one direct child, then prove it did not resolve through a link."""

    try:
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
    except FileExistsError as error:
        raise GrammarStdlibAccuracyError(f"{label} already exists") from error
    _assert_direct_directory(path, label)


def _assert_run_ancestors(run_dir: Path, *, allow_missing: bool) -> None:
    if run_dir.parent != RUN_ROOT:
        raise GrammarStdlibAccuracyError("run directory escaped the fixed D18 root")
    _assert_direct_directory(PROJECT_ROOT, "project root")
    artifacts = PROJECT_ROOT / "artifacts"
    _assert_direct_directory(artifacts, "artifact root")
    grammar_root = artifacts / "grammar-stdlib-accuracy"
    for path, label in ((grammar_root, "grammar artifact root"), (RUN_ROOT, "D18 artifact root")):
        if path.exists() or path.is_symlink():
            _assert_direct_directory(path, label)
        elif allow_missing:
            _create_direct_directory(path, label)
        else:
            raise GrammarStdlibAccuracyError(f"{label} is unavailable")


def _prepare_run_root(run_dir: Path) -> None:
    _assert_run_ancestors(run_dir, allow_missing=True)
    _create_direct_directory(run_dir, "D18 run directory")
    for label in ("base", "adapter"):
        _create_direct_directory(run_dir / label, f"D18 run child {label}")
    if {path.name for path in run_dir.iterdir()} != {"base", "adapter"}:
        raise GrammarStdlibAccuracyError("D18 run child roster differs")


def _write_run_file(run_dir: Path, directory: Path, name: str, raw: bytes) -> Path:
    if directory not in {run_dir, run_dir / "base", run_dir / "adapter"}:
        raise GrammarStdlibAccuracyError("run file escaped the fixed D18 roster")
    if not raw or name not in {"candidates.jsonl", "report.json"}:
        raise GrammarStdlibAccuracyError("run file name or payload is invalid")
    _assert_run_ancestors(run_dir, allow_missing=False)
    _assert_direct_directory(run_dir, "D18 run directory")
    descriptor, initial_identity = _open_direct_directory(
        directory, f"run directory {directory.name}"
    )
    temporary = f".{name}.tmp-{os.getpid()}"
    temporary_created = False
    file_descriptor: int | None = None
    try:
        file_descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=descriptor,
        )
        temporary_created = True
        view = memoryview(raw)
        while view:
            written = os.write(file_descriptor, view)
            if written <= 0:
                raise GrammarStdlibAccuracyError("run file write made no progress")
            view = view[written:]
        os.fsync(file_descriptor)
        os.close(file_descriptor)
        file_descriptor = None
        os.link(
            temporary,
            name,
            src_dir_fd=descriptor,
            dst_dir_fd=descriptor,
            follow_symlinks=False,
        )
        os.unlink(temporary, dir_fd=descriptor)
        temporary_created = False
        os.fsync(descriptor)
        published = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        current = os.fstat(descriptor)
        named_directory = directory.lstat()
        if (
            not stat.S_ISREG(published.st_mode)
            or published.st_nlink != 1
            or published.st_size != len(raw)
            or _directory_identity(current) != initial_identity
            or _directory_identity(named_directory) != initial_identity
        ):
            raise GrammarStdlibAccuracyError("published run file or directory identity changed")
    except OSError as error:
        raise GrammarStdlibAccuracyError(f"cannot publish fixed run file {name}") from error
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if temporary_created:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=descriptor)
        os.close(descriptor)
    return directory / name


def _verify_worker_responses(
    tasks: list[Mapping[str, Any]], responses: list[Mapping[str, Any]]
) -> None:
    if len(responses) != len(tasks) or len(responses) != 18:
        raise GrammarStdlibAccuracyError("D18 worker response count differs from request roster")
    for task, response in zip(tasks, responses, strict=True):
        if (
            set(response) != {"request_id", "text", "peak_metal_gb"}
            or response.get("request_id") != task["task_id"]
            or not isinstance(response.get("text"), str)
            or not response["text"]
            or type(response.get("peak_metal_gb")) not in (int, float)
            or not 0 <= float(response["peak_metal_gb"]) <= qlora.LIMITS["metal_gb"]
        ):
            raise GrammarStdlibAccuracyError("D18 worker response roster or schema drift")


def _verify_run_roster(run_dir: Path) -> set[Path]:
    """Reject extra, linked, or special files before redacted evidence is emitted."""

    _assert_run_ancestors(run_dir, allow_missing=False)
    _assert_direct_directory(run_dir, "D18 run directory")
    expected = {
        run_dir / "base/candidates.jsonl",
        run_dir / "adapter/candidates.jsonl",
        run_dir / "report.json",
    }
    directories = {run_dir / "base", run_dir / "adapter"}
    actual_files: set[Path] = set()
    actual_directories: set[Path] = set()
    for path in run_dir.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise GrammarStdlibAccuracyError("ignored run tree contains a symlink")
        if stat.S_ISDIR(metadata.st_mode):
            actual_directories.add(path)
        elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
            actual_files.add(path)
        else:
            raise GrammarStdlibAccuracyError("ignored run tree contains a special or linked file")
    if actual_files != expected or actual_directories != directories:
        raise GrammarStdlibAccuracyError("ignored D18 run artifact roster differs")
    return expected


def run(args: argparse.Namespace) -> int:
    freeze_value, freeze_raw = _load(FREEZE_PATH, "D18 freeze")
    if safe._tracked_record(str(FREEZE_PATH.relative_to(PROJECT_ROOT)))["sha256"] != raw_hash(
        freeze_raw
    ):
        raise GrammarStdlibAccuracyError("freeze is not committed")
    head, tree = safe._require_published(
        str(freeze_value["remote"]), str(freeze_value["remote_ref"])
    )
    run_dir = _verify_freeze(freeze_value, head)
    tasks, truth_value, _task_raw = _verify_frozen_inputs(
        freeze_value, Path(args.metis_root), Path(args.node_path)
    )
    if run_dir.exists() or run_dir.is_symlink():
        raise GrammarStdlibAccuracyError("run directory already exists")
    porcelain_before = safe._git("status", "--porcelain", "--untracked-files=all")
    if porcelain_before:
        raise GrammarStdlibAccuracyError("worktree must remain clean before inference")
    qlora._metal_jit_sandbox_canary()
    _prepare_run_root(run_dir)
    requests = [
        {"request_id": task["task_id"], "messages": build_messages(task), "max_tokens": 512}
        for task in tasks
    ]
    truth_by_id = {item["task_id"]: item for item in truth_value["tasks"]}
    observations: dict[str, list[dict[str, Any]]] = {}
    outputs: dict[str, dict[str, Any]] = {}
    for label, adapter in (("base", False), ("adapter", True)):
        responses = qlora._bounded_worker(
            _worker_command(adapter), requests, qlora.LIMITS["hours"] * 3600
        )
        _verify_worker_responses(tasks, responses)
        candidate = _candidates(tasks, responses)
        path = _write_run_file(run_dir, run_dir / label, "candidates.jsonl", candidate)
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
    _verify_bound(list(freeze_value["bound_inputs"]))
    if safe._git("status", "--porcelain", "--untracked-files=all") != porcelain_before:
        raise GrammarStdlibAccuracyError("tracked worktree changed during model execution")
    decision = gate_arithmetic(observations["base"], observations["adapter"])
    report = {
        "schema_version": 1,
        "status": "complete",
        "authority_tier": "diagnostic_only",
        "head": head,
        "tree": tree,
        "freeze_sha256": freeze_value["freeze_sha256"],
        "outputs": outputs,
        "observations": observations,
        "decision": decision,
        "model_outputs_observed": True,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "nonclaims": NONCLAIMS,
    }
    report["report_sha256"] = canonical_hash(report)
    _write_run_file(run_dir, run_dir, "report.json", safe.canonical_bytes(report) + b"\n")
    _verify_run_roster(run_dir)
    print(
        json.dumps(
            {"event": "grammar_stdlib_d18_run", "verdict": decision["verdict"]}, sort_keys=True
        )
    )
    return 0 if decision["verdict"].endswith("PASS") else 1


def evidence(args: argparse.Namespace) -> int:
    if EVIDENCE_PATH.exists() or EVIDENCE_PATH.is_symlink():
        raise GrammarStdlibAccuracyError("evidence output already exists")
    freeze_value, raw_freeze = _load(FREEZE_PATH, "D18 freeze")
    if safe._tracked_record(str(FREEZE_PATH.relative_to(PROJECT_ROOT)))["sha256"] != raw_hash(
        raw_freeze
    ):
        raise GrammarStdlibAccuracyError("evidence freeze is not committed")
    head, tree = safe._require_published(
        str(freeze_value["remote"]), str(freeze_value["remote_ref"])
    )
    run_dir = _verify_freeze(freeze_value, head)
    tasks, truth_value, _task_raw = _verify_frozen_inputs(
        freeze_value, Path(args.metis_root), Path(args.node_path)
    )
    report, _ = _load(run_dir / "report.json", "D18 report")
    _self_hash(report, "report_sha256")
    if (
        report.get("head") != head
        or report.get("tree") != tree
        or report.get("freeze_sha256") != freeze_value.get("freeze_sha256")
    ):
        raise GrammarStdlibAccuracyError("run report lineage drift")
    _verify_run_roster(run_dir)
    truth_by_id = {item["task_id"]: item for item in truth_value["tasks"]}
    observations = {
        label: [
            score_candidate(
                task, row, truth_by_id[task["task_id"]], Path(args.metis_root), Path(args.node_path)
            )
            for task, row in zip(
                tasks, _read_candidates(run_dir / label / "candidates.jsonl", tasks), strict=True
            )
        ]
        for label in ("base", "adapter")
    }
    decision = gate_arithmetic(observations["base"], observations["adapter"])
    if report.get("observations") != observations or report.get("decision") != decision:
        raise GrammarStdlibAccuracyError("run report differs from independent rescore")
    body = {
        "schema_version": 1,
        "evidence_id": "grammar-stdlib-accuracy-d18-evaluation/v1",
        "status": "verified_local_cooperative",
        "authority_tier": "diagnostic_only",
        "execution": {
            "head": head,
            "tree": tree,
            "freeze_sha256": freeze_value["freeze_sha256"],
            "freeze_file_sha256": raw_hash(raw_freeze),
            "report_sha256": report["report_sha256"],
            "run_dir": str(run_dir.relative_to(PROJECT_ROOT)),
            "outputs": report["outputs"],
        },
        "observations": {
            label: [
                {
                    key: row[key]
                    for key in (
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
                    )
                }
                for row in observations[label]
            ]
            for label in observations
        },
        "decision": decision,
        "model_outputs_observed": True,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "nonclaims": NONCLAIMS,
    }
    body["evaluation_sha256"] = canonical_hash(body)
    safe._atomic_json(EVIDENCE_PATH, body)
    print(
        json.dumps(
            {"event": "grammar_stdlib_d18_evidence", "verdict": decision["verdict"]}, sort_keys=True
        )
    )
    return 0 if decision["verdict"].endswith("PASS") else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("mode", choices=("truth", "freeze", "run", "evidence"))
    result.add_argument("--run-id")
    result.add_argument("--metis-root", type=Path, default=DEFAULT_METIS_ROOT)
    result.add_argument("--node-path", type=Path, default=DEFAULT_NODE)
    result.add_argument("--remote", default="origin")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.mode in {"freeze", "run", "evidence"} and not args.run_id and args.mode == "freeze":
        print("error: freeze requires --run-id", file=sys.stderr)
        return 2
    try:
        return {"truth": truth, "freeze": freeze, "run": run, "evidence": evidence}[args.mode](args)
    except (
        GrammarStdlibAccuracyError,
        qlora.RuntimeContractError,
        oracle.GrammarStdlibOracleError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
