"""Project one consumed successor run into redacted, terminal evidence.

The run directory is ignored and may contain generated text.  This module
accepts only its exact one-use tree and emits tracked receipts with identities,
hashes, counters, and redacted structural failure codes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from metis_model1 import catalog_maintenance_successor as successor

ROOT = Path(__file__).resolve().parents[2]
RUN_RELATIVE = "artifacts/catalog-maintenance-successor-v1"
FREEZE_RELATIVE = "manifests/catalog-maintenance-successor-freeze-v1.json"
EVALUATION_RELATIVE = "manifests/catalog-maintenance-successor-evaluation-v1.json"
DECISION_RELATIVE = "manifests/catalog-maintenance-successor-decision-v1.json"
EVALUATION_SCHEMA_RELATIVE = "schemas/catalog-maintenance-successor-evaluation.schema.json"
DECISION_SCHEMA_RELATIVE = "schemas/catalog-maintenance-successor-decision.schema.json"

DEFAULT_RUN_DIR = ROOT / RUN_RELATIVE
DEFAULT_FREEZE = ROOT / FREEZE_RELATIVE
DEFAULT_EVALUATION = ROOT / EVALUATION_RELATIVE
DEFAULT_DECISION = ROOT / DECISION_RELATIVE
EVALUATION_SCHEMA = ROOT / EVALUATION_SCHEMA_RELATIVE
DECISION_SCHEMA = ROOT / DECISION_SCHEMA_RELATIVE

SCORE_KEYS = (
    "semantic_correct",
    "critical_failure",
    "invented_values",
    "legacy_inline",
    "retrieval_error",
    "skeleton_match",
)
FULL_SCORE_KEYS = {
    *SCORE_KEYS,
    "required_missing",
    "forbidden_hits",
    "retrieval_error_text",
}
VETO_KEYS = ("critical_failure", "invented_values", "legacy_inline", "retrieval_error")
NONCLAIMS = [
    "no_accuracy_claim",
    "no_promotion_claim",
    "no_training_authority",
    "no_tenant_dataset_authority",
    "no_independent_accuracy_denominator",
    "no_live_execution_attestation",
    "nonpromotable",
]
RAW_KEYS = {
    "text",
    "messages",
    "expected_source",
    "expected_skeleton",
    "source",
    "before_source",
    "retrieval_error_text",
    "required_missing",
    "forbidden_hits",
}
SAFE_FAILURE_CODES = {
    "missing_metis_0_43_prefix",
    "multiple_code_fences",
    "text_outside_code_fence",
    "unbalanced_code_fence",
    "catalog describe rejected candidate",
}


class SuccessorEvidenceError(ValueError):
    """Raised when a successor run cannot be turned into terminal evidence."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def raw_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(_regular_bytes(path, str(path))).hexdigest()


def _regular_bytes(path: Path, label: str) -> bytes:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        metadata = os.fstat(descriptor)
    except OSError as error:
        raise SuccessorEvidenceError(f"{label} is unavailable") from error
    try:
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise SuccessorEvidenceError(f"{label} is not a singly linked regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    except OSError as error:
        raise SuccessorEvidenceError(f"{label} is unreadable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(_regular_bytes(path, label).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SuccessorEvidenceError(f"{label} is not JSON") from error
    if not isinstance(value, dict):
        raise SuccessorEvidenceError(f"{label} is not an object")
    return value


def _schema(path: Path, label: str) -> dict[str, Any]:
    value = _load(path, label)
    try:
        Draft202012Validator.check_schema(value)
    except Exception as error:  # noqa: BLE001 - schema is a fail-closed boundary
        raise SuccessorEvidenceError(f"{label} is invalid") from error
    return value


def _schema_for(root: Path, relative: str) -> Path:
    """Permit dry evidence tests to use the immutable project schema."""

    candidate = root / relative
    return candidate if candidate.is_file() else ROOT / relative


def _self_hash(document: Mapping[str, Any], field: str) -> str:
    return canonical_hash({key: value for key, value in document.items() if key != field})


def _contains_raw_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(key in RAW_KEYS or _contains_raw_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_raw_key(item) for item in value)
    return False


def _failure_codes(score: Mapping[str, Any]) -> list[str]:
    if int(score["semantic_correct"]) == 1:
        return []
    candidate = score.get("retrieval_error_text")
    if isinstance(candidate, str) and candidate in SAFE_FAILURE_CODES:
        return [candidate]
    return ["structural_or_oracle_failure"]


def _validated_score(value: Any, case_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != FULL_SCORE_KEYS:
        raise SuccessorEvidenceError(f"attempt score shape drift for {case_id}")
    projected: dict[str, Any] = {}
    for key in SCORE_KEYS:
        if key == "skeleton_match":
            if not isinstance(value[key], bool):
                raise SuccessorEvidenceError(f"final skeleton score is not boolean for {case_id}")
            projected[key] = value[key]
        else:
            if type(value[key]) is not int or value[key] not in {0, 1}:
                raise SuccessorEvidenceError(f"final score is not binary for {case_id}: {key}")
            projected[key] = value[key]
    for key in ("required_missing", "forbidden_hits"):
        if not isinstance(value[key], list) or any(
            not isinstance(fragment, str) for fragment in value[key]
        ):
            raise SuccessorEvidenceError(f"attempt score fragments are invalid for {case_id}")
    error_text = value["retrieval_error_text"]
    if error_text is not None and not isinstance(error_text, str):
        raise SuccessorEvidenceError(f"attempt error text is invalid for {case_id}")
    if value["retrieval_error"] != int(error_text is not None):
        raise SuccessorEvidenceError(f"attempt error counter is inconsistent for {case_id}")
    if value["semantic_correct"] == 1 and (
        value["skeleton_match"] is not True
        or value["critical_failure"] != 0
        or value["required_missing"]
        or value["forbidden_hits"]
        or error_text is not None
    ):
        raise SuccessorEvidenceError(f"attempt semantic score is inconsistent for {case_id}")
    return projected


def _final_score(attempts: Any, case_id: str) -> tuple[dict[str, Any], int]:
    if not isinstance(attempts, list) or not attempts:
        raise SuccessorEvidenceError(f"attempts missing for {case_id}")
    if [item.get("attempt") if isinstance(item, Mapping) else None for item in attempts] != list(
        range(len(attempts))
    ):
        raise SuccessorEvidenceError(f"attempt order drift for {case_id}")
    hashes: list[str] = []
    for index, item in enumerate(attempts):
        if not isinstance(item, Mapping) or set(item) != {
            "attempt",
            "text",
            "text_sha256",
            "receipt_sha256",
            "score",
        }:
            raise SuccessorEvidenceError(f"attempt shape drift for {case_id}")
        text, digest = item["text"], item["text_sha256"]
        if not isinstance(text, str) or not isinstance(digest, str):
            raise SuccessorEvidenceError(f"attempt text/hash missing for {case_id}")
        if digest != "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest():
            raise SuccessorEvidenceError(f"attempt text hash drift for {case_id}")
        hashes.append(digest)
        attempt_score = _validated_score(item["score"], case_id)
        if index < len(attempts) - 1 and attempt_score["semantic_correct"] == 1:
            raise SuccessorEvidenceError(f"attempts continue after success for {case_id}")
    projected = _validated_score(attempts[-1]["score"], case_id)
    return projected, len(set(hashes))


def _require_exact_run_tree(run_dir: Path, case_ids: list[str]) -> None:
    expected_directories = {".", "tasks", *(f"tasks/{case_id}" for case_id in case_ids)}
    expected_files = {
        "report.json",
        "worker.stderr.log",
        *(f"tasks/{case_id}/attempts.json" for case_id in case_ids),
    }
    try:
        root_stat = run_dir.lstat()
    except OSError as error:
        raise SuccessorEvidenceError("successor run directory is unavailable") from error
    if run_dir.is_symlink() or not stat.S_ISDIR(root_stat.st_mode):
        raise SuccessorEvidenceError("successor run directory is not a directory")
    seen_directories: set[str] = set()
    seen_files: set[str] = set()
    for current, directories, files in os.walk(run_dir, topdown=True, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(run_dir).as_posix()
        metadata = current_path.lstat()
        if current_path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            raise SuccessorEvidenceError("successor run tree has a symlink or non-directory")
        seen_directories.add(relative)
        for name in directories:
            child = current_path / name
            child_stat = child.lstat()
            if child.is_symlink() or not stat.S_ISDIR(child_stat.st_mode):
                raise SuccessorEvidenceError("successor run tree has a symlink or non-directory")
        for name in files:
            child = current_path / name
            child_stat = child.lstat()
            if (
                child.is_symlink()
                or not stat.S_ISREG(child_stat.st_mode)
                or child_stat.st_nlink != 1
            ):
                raise SuccessorEvidenceError(
                    "successor run tree has a non-regular or hard-linked file"
                )
            seen_files.add(child.relative_to(run_dir).as_posix())
    if seen_directories != expected_directories or seen_files != expected_files:
        raise SuccessorEvidenceError("successor run tree differs from the exact ten-file roster")


def _expected_roster(freeze: Mapping[str, Any]) -> list[tuple[str, str]]:
    tasks = freeze.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 8:
        raise SuccessorEvidenceError("freeze does not contain the exact eight tasks")
    roster = [
        (task.get("case_id"), task.get("root_id")) for task in tasks if isinstance(task, Mapping)
    ]
    if (
        len(roster) != 8
        or len(set(roster)) != 8
        or any(
            not isinstance(case_id, str) or not isinstance(root_id, str)
            for case_id, root_id in roster
        )
    ):
        raise SuccessorEvidenceError("freeze task roster is malformed")
    return [(str(case_id), str(root_id)) for case_id, root_id in roster]


def _verify_repository_state(
    root: Path,
    freeze: Mapping[str, Any],
    report: Mapping[str, Any],
    freeze_path: Path,
) -> None:
    """Reprove the published freeze and every bound input before redaction."""

    freeze_schema = successor.common._schema(
        root / successor.FREEZE_SCHEMA.relative_to(successor.PROJECT_ROOT),
        successor.FREEZE_SCHEMA_SHA256,
        "successor freeze schema",
    )
    successor.common._validate(freeze, freeze_schema, "successor freeze")
    if successor.common._git_blob(root, FREEZE_RELATIVE) != raw_hash(freeze_path):
        raise SuccessorEvidenceError("successor freeze is not committed at HEAD")
    try:
        head, tree = successor.common.require_head_published(
            root, str(freeze["remote"]), str(freeze["remote_ref"])
        )
    except Exception as error:  # noqa: BLE001 - translate the authority boundary
        raise SuccessorEvidenceError("successor execution HEAD is not published") from error
    if report.get("head") != head or report.get("tree") != tree:
        raise SuccessorEvidenceError("successor report execution identity is not current HEAD")
    ancestor = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(root),
            "merge-base",
            "--is-ancestor",
            str(freeze["preimage_commit"]),
            head,
        ],
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    if ancestor.returncode != 0:
        raise SuccessorEvidenceError("successor preimage is not an execution ancestor")
    manifest, _schema_document, _cases = successor.load_probe_contract(root)
    bound = successor._bound_input_records(root, manifest)
    successor.common._require_bound_worktree_matches_head(root, bound)
    if bound != freeze.get("bound_inputs"):
        raise SuccessorEvidenceError("successor bound inputs differ from the freeze")


def build_evaluation_receipt(
    *,
    root: Path = ROOT,
    run_dir: Path | None = None,
    freeze_path: Path | None = None,
    verify_repository: bool = True,
) -> dict[str, Any]:
    run_dir = run_dir or root / RUN_RELATIVE
    freeze_path = freeze_path or root / FREEZE_RELATIVE
    report_path = run_dir / "report.json"
    stderr_path = run_dir / "worker.stderr.log"
    freeze = _load(freeze_path, "successor freeze")
    report = _load(report_path, "successor run report")
    if freeze.get("freeze_sha256") != _self_hash(freeze, "freeze_sha256"):
        raise SuccessorEvidenceError("successor freeze self-hash drift")
    if (
        freeze.get("status") != "frozen_before_model_output"
        or freeze.get("model_outputs_observed") is not False
    ):
        raise SuccessorEvidenceError("successor freeze is not pre-output")
    if freeze.get("training_authorized") is not False or freeze.get("run_dir") != RUN_RELATIVE:
        raise SuccessorEvidenceError("successor freeze authority or output path drift")
    if set(report) != {
        "schema_version",
        "status",
        "head",
        "tree",
        "freeze_sha256",
        "observations",
        "decision",
        "model_outputs_observed",
        "training_authorized",
    }:
        raise SuccessorEvidenceError("successor run report shape drift")
    if report.get("status") != "complete" or report.get("model_outputs_observed") is not True:
        raise SuccessorEvidenceError("successor run is incomplete")
    if (
        report.get("training_authorized") is not False
        or report.get("freeze_sha256") != freeze["freeze_sha256"]
    ):
        raise SuccessorEvidenceError("successor run authority or freeze binding drift")
    if verify_repository:
        _verify_repository_state(root, freeze, report, freeze_path)
    expected = _expected_roster(freeze)
    observations = report.get("observations")
    if not isinstance(observations, list):
        raise SuccessorEvidenceError("successor report observations are missing")
    actual = [
        (item.get("case_id"), item.get("root_id"))
        for item in observations
        if isinstance(item, Mapping)
    ]
    if actual != expected:
        raise SuccessorEvidenceError("successor report roster differs from its freeze")
    _require_exact_run_tree(run_dir, [case_id for case_id, _root_id in expected])

    safe_observations: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    totals = {key: 0 for key in ("cases_in", "cases_out", "cases_distinct", "gaps", *SCORE_KEYS)}
    for observation in observations:
        assert isinstance(observation, Mapping)  # guarded by exact roster construction
        case_id = str(observation["case_id"])
        if set(observation) != {"case_id", "root_id", *FULL_SCORE_KEYS}:
            raise SuccessorEvidenceError(f"report observation shape drift for {case_id}")
        attempts_path = run_dir / "tasks" / case_id / "attempts.json"
        try:
            attempts = json.loads(
                _regular_bytes(attempts_path, f"attempts {case_id}").decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SuccessorEvidenceError(f"attempts are not JSON for {case_id}") from error
        final_score, distinct_hashes = _final_score(attempts, case_id)
        source_score = attempts[-1]["score"]
        assert isinstance(source_score, Mapping)
        if any(observation.get(key) != source_score.get(key) for key in FULL_SCORE_KEYS):
            raise SuccessorEvidenceError(f"report/final score mismatch for {case_id}")
        safe = {
            "case_id": case_id,
            "root_id": str(observation["root_id"]),
            **{
                key: (final_score[key] if key == "skeleton_match" else int(final_score[key]))
                for key in SCORE_KEYS
            },
            "required_missing": list(source_score["required_missing"]),
            "forbidden_hits": list(source_score["forbidden_hits"]),
            "retrieval_error_text": source_score["retrieval_error_text"],
        }
        safe_observations.append(safe)
        cases.append(
            {
                "case_id": case_id,
                "root_id": str(observation["root_id"]),
                "attempts": len(attempts),
                "attempt_text_hashes_distinct": distinct_hashes,
                "attempts_file_sha256": raw_hash(attempts_path),
                "final_score": final_score,
                "failure_codes": _failure_codes(source_score),
            }
        )
        totals["cases_in"] += 1
        totals["cases_out"] += 1
        totals["cases_distinct"] += 1
        for key in SCORE_KEYS:
            totals[key] += int(final_score[key])
    totals["gaps"] = 8 - totals["cases_distinct"]
    derived = successor.gate_arithmetic(safe_observations)
    if report.get("decision") != derived:
        raise SuccessorEvidenceError("successor report decision does not recompute from attempts")
    verdict = derived["verdict"]
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "status": "verified_local_cooperative",
        "authority_scope": "public_synthetic_prompt_cure_execution_only",
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
        "counts": totals,
        "veto_counts": {key: totals[key] for key in VETO_KEYS},
        "model": {
            key: freeze["model"][key]
            for key in ("family", "adapter_enabled", "temperature", "seed")
        },
        "policy": {
            "verdict": verdict,
            "failure_action": "no_retrain_prompt_cure"
            if verdict == "NO_RETRAIN_PROMPT_CURE"
            else "diagnostic_only",
            "training_authorized": False,
            "promotion_claim": False,
            "accuracy_claim": False,
        },
        "nonclaims": NONCLAIMS,
    }
    receipt["evaluation_sha256"] = canonical_hash(receipt)
    if _contains_raw_key(receipt):
        raise SuccessorEvidenceError("generated evaluation contains raw model or oracle text")
    errors = validate_evaluation_receipt(receipt, root=root, freeze_path=freeze_path)
    if errors:
        raise SuccessorEvidenceError("generated successor evaluation invalid: " + "; ".join(errors))
    return receipt


def validate_evaluation_receipt(
    document: Mapping[str, Any], *, root: Path = ROOT, freeze_path: Path | None = None
) -> list[str]:
    errors = [
        error.message
        for error in Draft202012Validator(
            _schema(_schema_for(root, EVALUATION_SCHEMA_RELATIVE), "evaluation schema")
        ).iter_errors(document)
    ]
    if document.get("evaluation_sha256") != _self_hash(document, "evaluation_sha256"):
        errors.append("successor evaluation self-hash drift")
    if _contains_raw_key(document):
        errors.append("successor evaluation contains raw model or oracle text")
    try:
        freeze_path = freeze_path or root / FREEZE_RELATIVE
        freeze = _load(freeze_path, "successor freeze")
        roster = document["roster"]["cases"]
        expected = _expected_roster(freeze)
        actual = [(case["case_id"], case["root_id"]) for case in roster]
        if actual != expected:
            errors.append("successor evaluation roster differs from its freeze")
        execution = document["execution"]
        for key in ("freeze_sha256", "preimage_commit", "preimage_tree", "run_dir"):
            if execution.get(key) != freeze.get(key):
                errors.append(f"successor evaluation {key} differs from its freeze")
        if execution.get("freeze_raw_sha256") != raw_hash(freeze_path):
            errors.append("successor evaluation freeze raw hash differs from its freeze")
        totals = {
            key: 0 for key in ("cases_in", "cases_out", "cases_distinct", "gaps", *SCORE_KEYS)
        }
        for case in roster:
            if case["attempt_text_hashes_distinct"] > case["attempts"]:
                errors.append(
                    f"successor distinct attempt hashes exceed attempts: {case['case_id']}"
                )
            totals["cases_in"] += 1
            totals["cases_out"] += 1
            totals["cases_distinct"] += 1
            for key in SCORE_KEYS:
                totals[key] += int(case["final_score"][key])
            expected_failures = 0 if case["final_score"]["semantic_correct"] == 1 else 1
            if len(case["failure_codes"]) != expected_failures:
                errors.append(f"successor failure-code cardinality drift: {case['case_id']}")
            if case["final_score"]["semantic_correct"] == 1 and (
                case["final_score"]["skeleton_match"] is not True
                or any(case["final_score"][key] != 0 for key in VETO_KEYS)
            ):
                errors.append(f"successor green score is inconsistent: {case['case_id']}")
        totals["gaps"] = 8 - totals["cases_distinct"]
        if document.get("counts") != totals:
            errors.append("successor evaluation counts do not recompute from roster")
        if document.get("veto_counts") != {key: totals[key] for key in VETO_KEYS}:
            errors.append("successor evaluation veto counts do not recompute from roster")
        expected_verdict = (
            "NO_RETRAIN_PROMPT_CURE"
            if (
                totals["semantic_correct"] == 8
                and totals["skeleton_match"] == 8
                and all(totals[key] == 0 for key in VETO_KEYS)
            )
            else "DIAGNOSE"
        )
        if document.get("policy", {}).get("verdict") != expected_verdict:
            errors.append("successor evaluation verdict does not recompute from roster")
        expected_action = (
            "no_retrain_prompt_cure"
            if expected_verdict == "NO_RETRAIN_PROMPT_CURE"
            else "diagnostic_only"
        )
        if document.get("policy", {}).get("failure_action") != expected_action:
            errors.append("successor evaluation action does not match its verdict")
    except (KeyError, TypeError, ValueError, OSError, SuccessorEvidenceError) as error:
        errors.append(f"successor evaluation semantic validation failed: {type(error).__name__}")
    return sorted(errors)


def build_decision(
    receipt: Mapping[str, Any], *, evaluation_path: Path = DEFAULT_EVALUATION, root: Path = ROOT
) -> dict[str, Any]:
    if receipt.get("status") != "verified_local_cooperative":
        raise SuccessorEvidenceError("successor decision requires a verified receipt")
    verdict = receipt.get("policy", {}).get("verdict")
    if verdict not in {"NO_RETRAIN_PROMPT_CURE", "DIAGNOSE"}:
        raise SuccessorEvidenceError("successor decision has an invalid verdict")
    counts = receipt["counts"]
    decision: dict[str, Any] = {
        "schema_version": 1,
        "status": verdict,
        "authority_scope": "public_synthetic_prompt_cure_execution_only",
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
        "training_authorized": False,
        "auto_qlora_authorized": False,
        "promotion_claim": False,
        "accuracy_claim": False,
        "nonclaims": NONCLAIMS,
    }
    decision["decision_sha256"] = canonical_hash(decision)
    if _contains_raw_key(decision):
        raise SuccessorEvidenceError(
            "generated successor decision contains raw model or oracle text"
        )
    errors = validate_decision(decision, root=root, evaluation_path=evaluation_path)
    if errors:
        raise SuccessorEvidenceError("generated successor decision invalid: " + "; ".join(errors))
    return decision


def validate_decision(
    document: Mapping[str, Any], *, root: Path = ROOT, evaluation_path: Path | None = None
) -> list[str]:
    errors = [
        error.message
        for error in Draft202012Validator(
            _schema(_schema_for(root, DECISION_SCHEMA_RELATIVE), "decision schema")
        ).iter_errors(document)
    ]
    if document.get("decision_sha256") != _self_hash(document, "decision_sha256"):
        errors.append("successor decision self-hash drift")
    if _contains_raw_key(document):
        errors.append("successor decision contains raw model or oracle text")
    try:
        evaluation_path = evaluation_path or root / EVALUATION_RELATIVE
        evaluation = _load(evaluation_path, "successor evaluation")
        counts = evaluation["counts"]
        verdict = evaluation["policy"]["verdict"]
        if document.get("evaluation_receipt_sha256") != raw_hash(evaluation_path):
            errors.append("successor decision evaluation raw hash differs from receipt")
        if document.get("status") != verdict:
            errors.append("successor decision verdict differs from receipt")
        if document.get("freeze_sha256") != evaluation["execution"]["freeze_sha256"]:
            errors.append("successor decision freeze hash differs from receipt")
        if (
            document.get("execution_head") != evaluation["execution"]["head"]
            or document.get("execution_tree") != evaluation["execution"]["tree"]
        ):
            errors.append("successor decision execution identity differs from receipt")
        if document.get("result") != {
            "cases": 8,
            "semantic_correct": counts["semantic_correct"],
            "critical_failure": counts["critical_failure"],
            "invented_values": counts["invented_values"],
            "legacy_inline": counts["legacy_inline"],
            "retrieval_error": counts["retrieval_error"],
        }:
            errors.append("successor decision result differs from receipt")
        if any(
            document.get(key) is not False
            for key in (
                "training_authorized",
                "auto_qlora_authorized",
                "promotion_claim",
                "accuracy_claim",
            )
        ):
            errors.append("successor decision authority laundering")
    except (KeyError, TypeError, ValueError, OSError, SuccessorEvidenceError) as error:
        errors.append(f"successor decision semantic validation failed: {type(error).__name__}")
    return sorted(errors)


def write_evidence(
    *, root: Path = ROOT, verify_repository: bool = True
) -> tuple[dict[str, Any], dict[str, Any]]:
    evaluation_path = root / EVALUATION_RELATIVE
    decision_path = root / DECISION_RELATIVE
    evaluation_exists = evaluation_path.exists()
    decision_exists = decision_path.exists()
    if evaluation_exists and decision_exists:
        raise SuccessorEvidenceError("successor terminal evidence already exists")
    if decision_exists:
        raise SuccessorEvidenceError("successor decision exists without its evaluation")
    if evaluation_exists:
        evaluation = _load(evaluation_path, "partial successor evaluation")
        errors = validate_evaluation_receipt(evaluation, root=root)
        if errors:
            raise SuccessorEvidenceError(
                "partial successor evaluation is invalid: " + "; ".join(sorted(errors))
            )
        decision = build_decision(evaluation, evaluation_path=evaluation_path, root=root)
        successor.common._atomic_write(decision_path, canonical_bytes(decision) + b"\n")
        return evaluation, decision

    evaluation = build_evaluation_receipt(root=root, verify_repository=verify_repository)
    evaluation_raw = canonical_bytes(evaluation) + b"\n"
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=evaluation_path.parent, prefix=".catalog-successor-evidence-"
    ) as staging_raw:
        staging = Path(staging_raw)
        staged_evaluation = staging / evaluation_path.name
        staged_decision = staging / decision_path.name
        successor.common._atomic_write(staged_evaluation, evaluation_raw)
        decision = build_decision(evaluation, evaluation_path=staged_evaluation, root=root)
        decision_raw = canonical_bytes(decision) + b"\n"
        successor.common._atomic_write(staged_decision, decision_raw)
        os.replace(staged_evaluation, evaluation_path)
        os.replace(staged_decision, decision_path)
        return evaluation, decision


def verify_evidence(*, root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    evaluation_path = root / EVALUATION_RELATIVE
    decision_path = root / DECISION_RELATIVE
    actual_evaluation = _load(evaluation_path, "successor evaluation")
    actual_decision = _load(decision_path, "successor decision")
    errors = validate_evaluation_receipt(actual_evaluation, root=root)
    errors.extend(validate_decision(actual_decision, root=root, evaluation_path=evaluation_path))
    if errors:
        raise SuccessorEvidenceError(
            "successor terminal evidence is invalid: " + "; ".join(sorted(errors))
        )
    return actual_evaluation, actual_decision


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("mode", choices=("build", "verify"))
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        evaluation, decision = write_evidence() if args.mode == "build" else verify_evidence()
        print(
            json.dumps(
                {
                    "event": f"successor_evidence_{args.mode}_complete",
                    "verdict": decision["status"],
                    "semantic_correct": evaluation["counts"]["semantic_correct"],
                    "training_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as error:  # noqa: BLE001 - fail-closed CLI boundary
        print(
            json.dumps(
                {
                    "status": "STOP_TECHNICAL",
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
