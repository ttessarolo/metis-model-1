"""Build redacted, tracked evidence for one completed catalog probe.

The raw run stays under ignored ``artifacts/``.  This module deliberately
projects only hashes, identities, case ids/roots, attempt counts, and final
score counters into tracked JSON; model prompts and generated text never cross
the evidence boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_DIR = ROOT / "artifacts/catalog-maintenance-probe-v1"
DEFAULT_FREEZE = ROOT / "manifests/catalog-maintenance-probe-freeze-v1.json"
DEFAULT_EVALUATION = ROOT / "manifests/catalog-maintenance-probe-evaluation-v1.json"
DEFAULT_DECISION = ROOT / "manifests/catalog-maintenance-probe-decision-v1.json"
EVALUATION_SCHEMA = ROOT / "schemas/catalog-maintenance-probe-evaluation.schema.json"
DECISION_SCHEMA = ROOT / "schemas/catalog-maintenance-probe-decision.schema.json"

CASE_SCORE_KEYS = (
    "semantic_correct",
    "critical_failure",
    "invented_values",
    "legacy_inline",
    "retrieval_error",
    "skeleton_match",
)
VETO_KEYS = ("critical_failure", "invented_values", "legacy_inline", "retrieval_error")
NONCLAIMS = [
    "no_accuracy_claim",
    "no_promotion_claim",
    "no_training_authority",
    "no_tenant_dataset_authority",
    "no_independent_accuracy_denominator",
]


class EvidenceError(ValueError):
    """Raised when raw evidence cannot be projected fail-closed."""


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))).encode(
        "utf-8"
    )


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def raw_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceError(f"{path} is not an object")
    return value


def _self_hash(document: Mapping[str, Any], field: str) -> str:
    body = {key: value for key, value in document.items() if key != field}
    return canonical_hash(body)


def _schema(path: Path) -> dict[str, Any]:
    value = _load(path)
    try:
        Draft202012Validator.check_schema(value)
    except Exception as error:  # noqa: BLE001 - schema boundary is fail-closed
        raise EvidenceError(f"invalid evidence schema: {path}") from error
    return value


def validate_evaluation_receipt(document: Mapping[str, Any]) -> list[str]:
    errors = [
        error.message
        for error in Draft202012Validator(_schema(EVALUATION_SCHEMA)).iter_errors(document)
    ]
    if document.get("evaluation_sha256") != _self_hash(document, "evaluation_sha256"):
        errors.append("evaluation self-hash drift")
    try:
        freeze = _load(DEFAULT_FREEZE)
        execution = document["execution"]
        roster = document["roster"]
        cases = roster["cases"]
        expected_roster = [(task["case_id"], task["root_id"]) for task in freeze["tasks"]]
        actual_roster = [(case["case_id"], case["root_id"]) for case in cases]
        if actual_roster != expected_roster:
            errors.append("evaluation roster differs from the frozen task order")
        if len({case["case_id"] for case in cases}) != 8:
            errors.append("evaluation case ids are not eight distinct values")
        if len({case["root_id"] for case in cases}) != 8:
            errors.append("evaluation root ids are not eight distinct values")
        if execution.get("freeze_sha256") != freeze.get("freeze_sha256"):
            errors.append("evaluation freeze self-hash differs from the tracked freeze")
        if execution.get("freeze_raw_sha256") != raw_hash(DEFAULT_FREEZE):
            errors.append("evaluation freeze raw hash differs from the tracked freeze")
        if execution.get("preimage_commit") != freeze.get("preimage_commit"):
            errors.append("evaluation preimage commit differs from the tracked freeze")
        if execution.get("preimage_tree") != freeze.get("preimage_tree"):
            errors.append("evaluation preimage tree differs from the tracked freeze")
        if execution.get("run_dir") != freeze.get("run_dir"):
            errors.append("evaluation run directory differs from the tracked freeze")
        if document.get("model") != {
            key: freeze["model"][key]
            for key in ("family", "adapter_enabled", "temperature", "seed")
        }:
            errors.append("evaluation model identity differs from the tracked freeze")
        totals = {
            "cases_in": len(cases),
            "cases_out": len(cases),
            "cases_distinct": len({case["case_id"] for case in cases}),
            "gaps": 8 - len({case["case_id"] for case in cases}),
            **{key: 0 for key in CASE_SCORE_KEYS},
        }
        for case in cases:
            if case["attempt_text_hashes_distinct"] > case["attempts"]:
                errors.append(f"distinct attempt hashes exceed attempts: {case['case_id']}")
            for key in CASE_SCORE_KEYS:
                totals[key] += int(case["final_score"][key])
        if document.get("counts") != totals:
            errors.append("evaluation counts do not recompute from the tracked roster")
        if document.get("veto_counts") != {key: totals[key] for key in VETO_KEYS}:
            errors.append("evaluation veto counts do not recompute from the tracked roster")
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
        errors.append(f"evaluation semantic validation failed: {type(error).__name__}")
    return sorted(errors)


def validate_decision(document: Mapping[str, Any]) -> list[str]:
    errors = [
        error.message
        for error in Draft202012Validator(_schema(DECISION_SCHEMA)).iter_errors(document)
    ]
    if document.get("decision_sha256") != _self_hash(document, "decision_sha256"):
        errors.append("decision self-hash drift")
    try:
        evaluation = _load(DEFAULT_EVALUATION)
        counts = evaluation["counts"]
        compatible = [
            case
            for case in evaluation["roster"]["cases"]
            if not case["final_score"]["semantic_correct"]
            and not case["final_score"]["critical_failure"]
            and not case["final_score"]["retrieval_error"]
        ]
        compatible_roots = len({case["root_id"] for case in compatible})
        expected_delta = {
            "eligible": len(compatible) >= 3 and compatible_roots >= 2,
            "compatible_failures": len(compatible),
            "distinct_roots": compatible_roots,
            "reason": "all observed failures are critical or retrieval failures",
        }
        if document.get("evaluation_receipt_sha256") != raw_hash(DEFAULT_EVALUATION):
            errors.append("decision evaluation raw hash differs from the tracked receipt")
        if document.get("freeze_sha256") != evaluation["execution"]["freeze_sha256"]:
            errors.append("decision freeze hash differs from the tracked receipt")
        if document.get("execution_head") != evaluation["execution"]["head"]:
            errors.append("decision execution head differs from the tracked receipt")
        if document.get("execution_tree") != evaluation["execution"]["tree"]:
            errors.append("decision execution tree differs from the tracked receipt")
        if document.get("result") != {
            "cases": counts["cases_distinct"],
            "semantic_correct": counts["semantic_correct"],
            "critical_failure": counts["critical_failure"],
            "invented_values": counts["invented_values"],
            "legacy_inline": counts["legacy_inline"],
            "retrieval_error": counts["retrieval_error"],
        }:
            errors.append("decision result differs from the tracked receipt")
        if document.get("delta_qlora") != expected_delta:
            errors.append("decision delta eligibility does not recompute from the tracked receipt")
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
        errors.append(f"decision semantic validation failed: {type(error).__name__}")
    return sorted(errors)


def _final_score(attempts: list[dict[str, Any]], case_id: str) -> tuple[dict[str, Any], int]:
    if not attempts:
        raise EvidenceError(f"no attempts for {case_id}")
    expected_numbers = list(range(len(attempts)))
    if [item.get("attempt") for item in attempts] != expected_numbers:
        raise EvidenceError(f"attempt sequence drift for {case_id}")
    hashes = [item.get("text_sha256") for item in attempts]
    if any(not isinstance(value, str) or not value.startswith("sha256:") for value in hashes):
        raise EvidenceError(f"attempt text hash missing for {case_id}")
    for item in attempts:
        text = item.get("text")
        if not isinstance(text, str) or item["text_sha256"] != (
            "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        ):
            raise EvidenceError(f"attempt text hash drift for {case_id}")
    score = attempts[-1].get("score")
    if not isinstance(score, dict):
        raise EvidenceError(f"final score missing for {case_id}")
    return score, len(set(hashes))


def _require_exact_run_tree(run_dir: Path, case_ids: list[str]) -> None:
    expected_directories = {".", "tasks", *(f"tasks/{case_id}" for case_id in case_ids)}
    expected_files = {
        "report.json",
        "worker.stderr.log",
        *(f"tasks/{case_id}/attempts.json" for case_id in case_ids),
    }
    observed_directories: set[str] = set()
    observed_files: set[str] = set()
    for current, directories, files in os.walk(run_dir, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_directory = current_path.relative_to(run_dir).as_posix()
        metadata = current_path.lstat()
        if current_path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            raise EvidenceError("run tree contains a non-directory or symlink directory")
        observed_directories.add(relative_directory)
        for name in directories:
            child = current_path / name
            child_metadata = child.lstat()
            if child.is_symlink() or not stat.S_ISDIR(child_metadata.st_mode):
                raise EvidenceError("run tree contains a non-directory or symlink directory")
        for name in files:
            child = current_path / name
            child_metadata = child.lstat()
            if not stat.S_ISREG(child_metadata.st_mode) or child_metadata.st_nlink != 1:
                raise EvidenceError("run tree contains a non-regular or multiply-linked file")
            observed_files.add(child.relative_to(run_dir).as_posix())
    if observed_directories != expected_directories or observed_files != expected_files:
        raise EvidenceError("run tree differs from the exact ten-file evidence roster")


def build_evaluation_receipt(
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    freeze_path: Path = DEFAULT_FREEZE,
) -> dict[str, Any]:
    report_path = run_dir / "report.json"
    stderr_path = run_dir / "worker.stderr.log"
    report = _load(report_path)
    freeze = _load(freeze_path)
    if report.get("status") != "complete" or report.get("model_outputs_observed") is not True:
        raise EvidenceError("run is not a completed model-output run")
    if report.get("training_authorized") is not False:
        raise EvidenceError("raw run must not authorize training")
    if freeze.get("status") != "frozen_before_model_output":
        raise EvidenceError("freeze is not a pre-output freeze")
    if freeze.get("model_outputs_observed") is not False:
        raise EvidenceError("freeze already contains model outputs")
    if report.get("freeze_sha256") != freeze.get("freeze_sha256"):
        raise EvidenceError("run does not bind the current freeze")
    observations = report.get("observations")
    frozen_tasks = freeze.get("tasks")
    if not isinstance(observations, list) or not isinstance(frozen_tasks, list):
        raise EvidenceError("missing observation or frozen roster")
    expected = [(task.get("case_id"), task.get("root_id")) for task in frozen_tasks]
    actual = [(item.get("case_id"), item.get("root_id")) for item in observations]
    if expected != actual or len(actual) != 8 or len(set(actual)) != 8:
        raise EvidenceError("run roster is not the exact eight-case roster")
    _require_exact_run_tree(run_dir, [case_id for case_id, _root_id in actual])

    cases: list[dict[str, Any]] = []
    totals = {
        key: 0 for key in ("cases_in", "cases_out", "cases_distinct", "gaps", *CASE_SCORE_KEYS)
    }
    for observation in observations:
        case_id = observation["case_id"]
        attempts_path = run_dir / "tasks" / case_id / "attempts.json"
        attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
        if not isinstance(attempts, list):
            raise EvidenceError(f"attempt file is not a list: {case_id}")
        score, distinct_text_hashes = _final_score(attempts, case_id)
        for key in CASE_SCORE_KEYS:
            if key not in score:
                raise EvidenceError(f"score key missing: {case_id}/{key}")
            if int(score[key]) != int(observation[key]):
                raise EvidenceError(f"report/final score mismatch: {case_id}/{key}")
        cases.append(
            {
                "case_id": case_id,
                "root_id": observation["root_id"],
                "attempts": len(attempts),
                "attempt_text_hashes_distinct": distinct_text_hashes,
                "attempts_file_sha256": raw_hash(attempts_path),
                "final_score": {
                    key: (bool(score[key]) if key == "skeleton_match" else int(score[key]))
                    for key in CASE_SCORE_KEYS
                },
                "failure_codes": sorted(
                    {
                        str(score.get("retrieval_error_text"))
                        for score in [score]
                        if score.get("retrieval_error_text")
                    }
                ),
            }
        )
        totals["cases_in"] += 1
        totals["cases_out"] += 1
        totals["cases_distinct"] += 1
        for key in CASE_SCORE_KEYS:
            totals[key] += int(score[key])
    totals["gaps"] = 8 - totals["cases_distinct"]
    raw_counts = report.get("decision", {}).get("counts")
    expected_raw_counts = {
        key: totals[key]
        for key in (
            "cases_distinct",
            "cases_in",
            "cases_out",
            "critical_failure",
            "gaps",
            "invented_values",
            "legacy_inline",
            "retrieval_error",
            "semantic_correct",
        )
    }
    if raw_counts != expected_raw_counts:
        raise EvidenceError("report counts do not match final case scores")
    if totals["semantic_correct"] != 2 or any(totals[key] != raw_counts[key] for key in VETO_KEYS):
        raise EvidenceError("unexpected completed-probe arithmetic")

    receipt = {
        "schema_version": 1,
        "status": "verified_local_cooperative",
        "authority_scope": "public_synthetic_probe_execution_only",
        "execution": {
            "head": report["head"],
            "tree": report["tree"],
            "preimage_commit": freeze["preimage_commit"],
            "preimage_tree": freeze["preimage_tree"],
            "freeze_sha256": freeze["freeze_sha256"],
            "freeze_raw_sha256": raw_hash(freeze_path),
            "report_sha256": raw_hash(report_path),
            "stderr_sha256": raw_hash(stderr_path),
            "run_dir": freeze["run_dir"],
        },
        "roster": {"cases_in": 8, "cases_out": 8, "cases_distinct": 8, "gaps": 0, "cases": cases},
        "counts": {key: totals[key] for key in totals},
        "veto_counts": {key: totals[key] for key in VETO_KEYS},
        "model": {"family": "Qwen3.8", "adapter_enabled": False, "temperature": 0, "seed": 17},
        "policy": {
            "verdict": "DIAGNOSE",
            "failure_action": "diagnostic_only",
            "training_authorized": False,
            "promotion_claim": False,
            "accuracy_claim": False,
        },
        "nonclaims": NONCLAIMS,
    }
    receipt["evaluation_sha256"] = canonical_hash(receipt)
    errors = validate_evaluation_receipt(receipt)
    if errors:
        raise EvidenceError("generated evaluation receipt invalid: " + "; ".join(errors))
    return receipt


def build_decision(
    receipt: Mapping[str, Any], *, evaluation_path: Path = DEFAULT_EVALUATION
) -> dict[str, Any]:
    if receipt.get("status") != "verified_local_cooperative":
        raise EvidenceError("decision requires a verified evaluation receipt")
    if receipt.get("policy", {}).get("verdict") != "DIAGNOSE":
        raise EvidenceError("decision is only for DIAGNOSE")
    counts = receipt["counts"]
    compatible = [
        case
        for case in receipt["roster"]["cases"]
        if not case["final_score"]["semantic_correct"]
        and not case["final_score"]["critical_failure"]
        and not case["final_score"]["retrieval_error"]
    ]
    compatible_roots = len({case["root_id"] for case in compatible})
    decision = {
        "schema_version": 1,
        "status": "DIAGNOSE",
        "authority_scope": "public_synthetic_probe_execution_only",
        "evaluation_receipt_sha256": raw_hash(evaluation_path),
        "freeze_sha256": receipt["execution"]["freeze_sha256"],
        "execution_head": receipt["execution"]["head"],
        "execution_tree": receipt["execution"]["tree"],
        "result": {
            "cases": 8,
            "semantic_correct": counts["semantic_correct"],
            "critical_failure": counts["critical_failure"],
            "invented_values": counts["invented_values"],
            "legacy_inline": counts["legacy_inline"],
            "retrieval_error": counts["retrieval_error"],
        },
        "delta_qlora": {
            "eligible": len(compatible) >= 3 and compatible_roots >= 2,
            "compatible_failures": len(compatible),
            "distinct_roots": compatible_roots,
            "reason": "all observed failures are critical or retrieval failures",
        },
        "training_authorized": False,
        "auto_qlora_authorized": False,
        "promotion_claim": False,
        "accuracy_claim": False,
        "nonclaims": NONCLAIMS,
    }
    decision["decision_sha256"] = canonical_hash(decision)
    errors = validate_decision(decision)
    if errors:
        raise EvidenceError("generated decision invalid: " + "; ".join(errors))
    return decision


def write_evidence(*, root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    run_dir = root / "artifacts/catalog-maintenance-probe-v1"
    freeze = root / "manifests/catalog-maintenance-probe-freeze-v1.json"
    evaluation_path = root / "manifests/catalog-maintenance-probe-evaluation-v1.json"
    decision_path = root / "manifests/catalog-maintenance-probe-decision-v1.json"
    evaluation = build_evaluation_receipt(run_dir=run_dir, freeze_path=freeze)
    evaluation_path.write_bytes(canonical_bytes(evaluation) + b"\n")
    decision = build_decision(evaluation, evaluation_path=evaluation_path)
    decision_path.write_bytes(canonical_bytes(decision) + b"\n")
    return evaluation, decision


if __name__ == "__main__":
    evaluation, decision = write_evidence()
    print(
        json.dumps(
            {
                "evaluation_sha256": evaluation["evaluation_sha256"],
                "decision_sha256": decision["decision_sha256"],
            },
            sort_keys=True,
        )
    )
