"""Terminal adapter-on replay of the already-frozen W5-XS B12 surface.

B12 is deliberately downstream of checkpoint selection.  This module never
reads the training dataset and its receipt states that it cannot feed training
or selection.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import re
import select
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metis_model1.initial_local_qlora_runtime import (
    EVALUATION_CACHE_ROOT,
    EVALUATION_SANDBOX_POLICY,
    LIMITS,
    SANDBOX_EXEC,
    RuntimeContractError,
    _atomic_write,
    _canonical_hash,
    _evaluation_environment,
    _prefixed_sha256,
    _terminate_process_group,
    verify_adapter_off_restore_receipt,
    verify_selection_receipt,
)
from metis_model1.oracles import (
    RUNNER_PATH,
    build_oracle_request,
    run_oracle,
    validate_pinned_metis,
    verify_oracle_envelope,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DELIVERY_ROOT = PROJECT_ROOT / "artifacts/w5-xs/2026-08-24-delivery"
DEFAULT_ROSTER = DELIVERY_ROOT / "b12-roster-v2.json"
DEFAULT_FREEZE = DELIVERY_ROOT / "freeze-v4/freeze.json"
DEFAULT_BASELINE = DELIVERY_ROOT / "b12-run-v4/baseline-b12.json"
DEFAULT_METIS_ROOT = DELIVERY_ROOT / "metis-pinned"
DEFAULT_MODEL = PROJECT_ROOT / "artifacts/w4/2026-08-20-qualification/checkpoint"
DEFAULT_WORKER_PYTHON = PROJECT_ROOT / "qualification/.venv/bin/python"
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts/initial-local-qlora-v1/run-v1/b12-adapter"
DEFAULT_DATASET_RECEIPT = PROJECT_ROOT / "artifacts/initial-local-qlora-v1/dataset/receipt.json"
DEFAULT_RESTORE_RECEIPT = (
    PROJECT_ROOT / "artifacts/initial-local-qlora-v1/run-v1/adapter-off-restore.json"
)
ROSTER_FILE_SHA256 = "sha256:1459d1fa171b9f124c016aabed559081c9d3e7ca34db6d31b7285e692b175e6d"
FREEZE_FILE_SHA256 = "sha256:d61efffcca96947c23c43f956e20f49137ccd1956637be588a0886933d115c33"
FREEZE_SHA256 = "sha256:5b2c59f93b3e9f9ef3474be6fdd148833ebb395289c56f79d0deb380c7ee2960"
BASELINE_FILE_SHA256 = "sha256:57e5e739403ead63fd3c9463399d802f339a4a25ced4eed48cc61b4ed2355f50"
BASELINE_REPORT_SHA256 = "sha256:d218de259241735b348e6fe61b14af91eeddaa2afabb851c95259626ae827c8a"
FAMILIES = ("F-1", "F-2", "F-3")
SOURCE_RE = re.compile(r"```(?:metis)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


class B12ReplayError(ValueError):
    """Raised when the terminal B12 contract cannot be satisfied."""


def _fail(message: str) -> None:
    raise B12ReplayError(message)


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        _fail(f"required JSON is missing or unsafe: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        _fail(f"invalid JSON {path}: {exc}")
    if not isinstance(value, dict):
        _fail(f"JSON object required: {path}")
    return value


def _under_artifacts(path: Path) -> Path:
    if path.is_symlink():
        _fail("artifact path must not be a symlink")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to((PROJECT_ROOT / "artifacts").resolve())
    except ValueError:
        _fail("B12 path must stay below artifacts")
    return resolved


def _git_identity(root: Path) -> dict[str, str]:
    def git(*args: str) -> bytes:
        try:
            return subprocess.check_output(
                ["git", "-C", str(root), *args], stderr=subprocess.STDOUT, timeout=30
            )
        except (OSError, subprocess.SubprocessError) as exc:
            _fail(f"cannot inspect Git identity for {root}: {exc}")

    status = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    return {
        "head": git("rev-parse", "HEAD").strip().decode("ascii"),
        "tree": git("rev-parse", "HEAD^{tree}").strip().decode("ascii"),
        "status_sha256": "sha256:" + hashlib.sha256(status).hexdigest(),
    }


def _without_provenance(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_provenance(item) for key, item in value.items() if key != "provenance"
        }
    if isinstance(value, list):
        return [_without_provenance(item) for item in value]
    return value


def _extract_source(text: str) -> tuple[str | None, str | None]:
    matches = list(SOURCE_RE.finditer(text))
    if len(matches) > 1:
        return None, "multiple_code_fences"
    if matches:
        match = matches[0]
        if text[: match.start()].strip() or text[match.end() :].strip():
            return None, "text_outside_code_fence"
        source = match.group(1).strip()
    else:
        source = text.strip()
    if not source.startswith("metis 0.43"):
        return None, "missing_metis_0_43_prefix"
    if "```" in source:
        return None, "unbalanced_code_fence"
    return source.rstrip() + "\n", None


def _diff_paths(left: Any, right: Any, path: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        result: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                result.append(child)
            else:
                result.extend(_diff_paths(left[key], right[key], child))
        return result
    if isinstance(left, list) and isinstance(right, list):
        result = []
        for index in range(max(len(left), len(right))):
            child = f"{path}[{index}]"
            if index >= len(left) or index >= len(right):
                result.append(child)
            else:
                result.extend(_diff_paths(left[index], right[index], child))
        return result
    return [] if left == right else [path]


def _load_contracts(
    roster_path: Path, freeze_path: Path, baseline_path: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    expected_files = (
        (roster_path, ROSTER_FILE_SHA256),
        (freeze_path, FREEZE_FILE_SHA256),
        (baseline_path, BASELINE_FILE_SHA256),
    )
    for path, digest in expected_files:
        if _prefixed_sha256(path) != digest:
            _fail(f"frozen B12 file identity drift: {path.name}")
    roster, freeze, baseline = (_json(path) for path, _ in expected_files)
    generation = roster.get("generation")
    if (
        roster.get("roster_id") != "w5-xs-b12/v2"
        or roster.get("status") != "pre_oracle_freeze"
        or roster.get("created_before_model_outputs") is not True
        or roster.get("model_output_derived") is not False
        or not isinstance(generation, dict)
        or generation
        != {
            "adapter_enabled": False,
            "temperature": 0.0,
            "seed": 17,
            "enable_thinking": False,
            "max_tokens": 512,
            "max_repair_cycles": 2,
        }
    ):
        _fail("frozen B12 roster contract drift")
    tasks = roster.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 12:
        _fail("B12 roster denominator drift")
    task_ids = [task.get("task_id") for task in tasks if isinstance(task, dict)]
    if len(task_ids) != 12 or len(set(task_ids)) != 12:
        _fail("B12 roster IDs are missing or duplicated")
    if Counter(task.get("family") for task in tasks) != Counter({family: 4 for family in FAMILIES}):
        _fail("B12 family denominator drift")
    freeze_body = {key: value for key, value in freeze.items() if key != "freeze_sha256"}
    frozen_tasks = freeze.get("tasks")
    if (
        freeze.get("freeze_sha256") != FREEZE_SHA256
        or freeze.get("freeze_sha256") != _canonical_hash(freeze_body)
        or freeze.get("status") != "frozen_before_model_output"
        or freeze.get("model_outputs_observed") is not False
        or freeze.get("roster_sha256") != ROSTER_FILE_SHA256
        or not isinstance(frozen_tasks, list)
        or [task.get("task_id") for task in frozen_tasks] != task_ids
    ):
        _fail("B12 freeze identity or order drift")
    for task in frozen_tasks:
        prompt = task.get("initial_prompt")
        if (
            not isinstance(prompt, str)
            or not prompt
            or task.get("initial_prompt_sha256") != _canonical_hash(prompt)
        ):
            _fail("B12 frozen prompt identity drift")
    baseline_body = {key: value for key, value in baseline.items() if key != "report_sha256"}
    counts = baseline.get("counts")
    if (
        baseline.get("report_sha256") != BASELINE_REPORT_SHA256
        or baseline.get("report_sha256") != _canonical_hash(baseline_body)
        or baseline.get("status") != "complete"
        or baseline.get("verdict") != "MODEL1_USABLE_LOCAL_NO_TRAIN"
        or not isinstance(counts, dict)
        or counts.get("semantic_correct") != 11
        or counts.get("in") != 12
        or counts.get("out") != 12
        or counts.get("distinct") != 12
        or counts.get("gaps") != 0
        or baseline.get("critical_failures") != []
        or baseline.get("accepted_invented_identifiers") != 0
    ):
        _fail("B12 historical baseline drift")
    return roster, freeze, baseline


def _selection(path: Path, adapter: Path, dataset_receipt: Path) -> dict[str, Any]:
    try:
        return verify_selection_receipt(path, adapter=adapter, dataset_receipt=dataset_receipt)
    except RuntimeContractError as error:
        _fail(f"adapter selection receipt failed strict verification: {error}")


def _score(
    task: Mapping[str, Any],
    frozen: Mapping[str, Any],
    source: str | None,
    result: Mapping[str, Any] | None,
    extraction_error: str | None,
) -> tuple[bool, str | None, dict[str, Any]]:
    if source is None:
        return False, "output_format", {"extraction_error": extraction_error}
    if result is None or result.get("status") != "ok":
        failure = result.get("failure") if isinstance(result, Mapping) else None
        category = failure.get("kind") if isinstance(failure, Mapping) else "compile"
        if category not in {"parse", "link", "validation", "compile"}:
            category = "compile"
        return False, category, {}
    ir, ast = result.get("ir"), result.get("ast")
    if (
        not isinstance(ir, Mapping)
        or not isinstance(ir.get("value"), Mapping)
        or not isinstance(ast, Mapping)
        or not isinstance(ast.get("inventory"), Mapping)
    ):
        return False, "compile", {"reason": "missing_structural_result"}
    actual_ir = _without_provenance(ir["value"])
    actual_ast = ast["inventory"]
    family = task["family"]
    truth = frozen.get("truth")
    if not isinstance(truth, Mapping):
        _fail("frozen B12 truth is malformed")
    if family == "F-1":
        expected = truth.get("target")
        minimal = True
        paths: list[str] = []
    elif family == "F-2":
        expected = truth.get("after")
        before = truth.get("before")
        if not isinstance(before, Mapping):
            _fail("frozen F-2 before truth is malformed")
        minimal = source.rstrip() == str(task.get("after_source", "")).rstrip()
        paths = _diff_paths(before.get("normalized_ir"), actual_ir)
        if not minimal or paths != task.get("expected_changed_paths"):
            return False, "patch_minimality", {"minimal": minimal, "changed_paths": paths}
    else:
        expected = truth.get("fixed")
        minimal = True
        paths = []
    if not isinstance(expected, Mapping):
        _fail("frozen B12 expected truth is malformed")
    ir_match = actual_ir == expected.get("normalized_ir")
    ast_match = actual_ast == expected.get("ast_inventory")
    details = {
        "ir_match": ir_match,
        "ast_match": ast_match,
        "minimal": minimal,
        "changed_paths": paths,
    }
    return (True, None, details) if ir_match and ast_match else (False, "semantic", details)


def _diagnostics(result: Mapping[str, Any] | None, error: str | None) -> str:
    if result is None:
        return f"Output-format diagnostic: {error or 'missing source'}."
    rows: list[str] = []
    diagnostics = result.get("diagnostics")
    if isinstance(diagnostics, Mapping) and isinstance(diagnostics.get("all"), list):
        for item in diagnostics["all"]:
            if isinstance(item, Mapping) and isinstance(item.get("message"), str):
                rows.append(f"{item.get('code') or 'diagnostic'}: {item['message']}")
    failure = result.get("failure")
    if isinstance(failure, Mapping) and isinstance(failure.get("message"), str):
        rows.append(f"{failure.get('kind', 'failure')}: {failure['message']}")
    return "\n".join(dict.fromkeys(rows)) or "Compiler rejected the candidate."


def _request(
    worker: subprocess.Popen[str], request: dict[str, Any], deadline: float
) -> dict[str, Any]:
    if worker.stdin is None or worker.stdout is None:
        _fail("B12 worker pipes are unavailable")
    worker.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
    worker.stdin.flush()
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not select.select([worker.stdout], [], [], remaining)[0]:
        _fail("B12 worker timed out")
    line = worker.stdout.readline()
    if not line:
        _fail(f"B12 worker exited unexpectedly with {worker.poll()}")
    try:
        response = json.loads(line)
    except json.JSONDecodeError as exc:
        _fail(f"B12 worker returned malformed JSON: {exc}")
    peak = response.get("peak_metal_gb") if isinstance(response, dict) else None
    if (
        not isinstance(response, dict)
        or set(response) != {"request_id", "text", "peak_metal_gb"}
        or response.get("request_id") != request["request_id"]
        or not isinstance(response.get("text"), str)
        or not response["text"]
        or len(response["text"].encode("utf-8")) > 1_000_000
        or type(peak) not in (int, float)
        or not math.isfinite(peak)
        or not 0 <= peak <= LIMITS["metal_gb"]
    ):
        _fail("B12 worker response contract mismatch")
    return response


def _evidence_records(output: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(output.rglob("*")):
        if path.is_dir():
            if path.is_symlink():
                _fail("B12 evidence contains a symlink directory")
            continue
        if (
            path.name == "receipt.json"
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_nlink != 1
        ):
            if path.name == "receipt.json" and path.is_file() and not path.is_symlink():
                continue
            _fail("B12 evidence contains an unsafe or unexpected entry")
        relative = path.relative_to(output).as_posix()
        records[relative] = {
            "bytes": path.stat().st_size,
            "sha256": _prefixed_sha256(path),
        }
    return records


def replay_b12(
    *,
    adapter: Path,
    selection_receipt: Path,
    dataset_receipt: Path = DEFAULT_DATASET_RECEIPT,
    restore_receipt: Path = DEFAULT_RESTORE_RECEIPT,
    model: Path = DEFAULT_MODEL,
    metis_root: Path = DEFAULT_METIS_ROOT,
    roster_path: Path = DEFAULT_ROSTER,
    freeze_path: Path = DEFAULT_FREEZE,
    baseline_path: Path = DEFAULT_BASELINE,
    output: Path = DEFAULT_OUTPUT,
    worker_python: Path = DEFAULT_WORKER_PYTHON,
    timeout: float = LIMITS["hours"] * 3600,
) -> dict[str, Any]:
    output = _under_artifacts(output)
    if not 0 < timeout <= LIMITS["hours"] * 3600:
        _fail("B12 timeout must stay within the four-hour cap")
    if output != DEFAULT_OUTPUT.resolve() or output.exists() or output.is_symlink():
        _fail("B12 output must be the absent fixed terminal path")
    roster, freeze, baseline = _load_contracts(roster_path, freeze_path, baseline_path)
    selection = _selection(selection_receipt, adapter, dataset_receipt)
    try:
        restore = verify_adapter_off_restore_receipt(
            restore_receipt,
            adapter=adapter,
            dataset_receipt=dataset_receipt,
            selection_receipt=selection_receipt,
        )
    except RuntimeContractError as error:
        _fail(f"adapter-off restore receipt failed strict verification: {error}")
    validate_pinned_metis(metis_root)
    before_project = _git_identity(PROJECT_ROOT)
    before_metis = _git_identity(metis_root)
    output.mkdir(parents=True)
    deadline = time.monotonic() + timeout
    stderr_path = output / "worker.stderr.log"
    if worker_python.is_symlink():
        target = worker_python.resolve(strict=True)
        if not target.is_file():
            _fail("qualification worker Python symlink target is unavailable")
    elif not worker_python.is_file():
        _fail("qualification worker Python is unavailable")
    worker_command = [
        str(SANDBOX_EXEC),
        "-p",
        EVALUATION_SANDBOX_POLICY,
        str(worker_python),
        str((PROJECT_ROOT / "src/metis_model1/initial_local_qlora_runtime.py").resolve()),
        "worker",
        "--model",
        str(model),
        "--adapter",
        str(adapter),
    ]
    frozen_by_id = {task["task_id"]: task for task in freeze["tasks"]}
    observations: list[dict[str, Any]] = []
    peak_metal = 0.0
    for path in (
        EVALUATION_CACHE_ROOT,
        EVALUATION_CACHE_ROOT / "home",
        EVALUATION_CACHE_ROOT / "tmp",
    ):
        path.mkdir(parents=True, exist_ok=True)
    with stderr_path.open("x", encoding="utf-8") as stderr:
        worker = subprocess.Popen(
            worker_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            bufsize=1,
            env=_evaluation_environment(),
            start_new_session=True,
        )
        try:
            for task in roster["tasks"]:
                frozen = frozen_by_id[task["task_id"]]
                messages = [{"role": "user", "content": frozen["initial_prompt"]}]
                attempts: list[dict[str, Any]] = []
                attempt_file_hashes: list[str] = []
                final_source: str | None = None
                final_result: Mapping[str, Any] | None = None
                final_error: str | None = None
                first_shot = False
                for attempt in range(roster["generation"]["max_repair_cycles"] + 1):
                    response = _request(
                        worker,
                        {
                            "request_id": f"{task['task_id']}:{attempt}",
                            "messages": messages,
                            "max_tokens": 512,
                        },
                        deadline,
                    )
                    peak_metal = max(peak_metal, float(response["peak_metal_gb"]))
                    response_file = output / "tasks" / task["task_id"] / f"response-{attempt}.json"
                    _atomic_write(
                        response_file,
                        (json.dumps(response, allow_nan=False, sort_keys=True) + "\n").encode(
                            "utf-8"
                        ),
                    )
                    source, extraction_error = _extract_source(response["text"])
                    result: Mapping[str, Any] | None = None
                    oracle_file: Path | None = None
                    if source is not None:
                        oracle_file = output / "tasks" / task["task_id"] / f"oracle-{attempt}.json"
                        envelope = run_oracle(
                            source,
                            metis_root=metis_root,
                            runner_path=RUNNER_PATH,
                            output_path=oracle_file,
                            filename=task["filename"],
                            execution_mode="endpoint",
                            endpoint=task["endpoint"],
                            workspace_sources=task["workspace_sources"],
                        )
                        result = envelope.get("result")
                    success, category, _details = _score(
                        task, frozen, source, result, extraction_error
                    )
                    if attempt == 0:
                        first_shot = success
                    attempt_body = {
                        "schema_version": 1,
                        "task_id": task["task_id"],
                        "attempt": attempt,
                        "messages_sha256": _canonical_hash(messages),
                        "response_sha256": _prefixed_sha256(response_file),
                        "source_sha256": _canonical_hash(source) if source else None,
                        "oracle_sha256": _prefixed_sha256(oracle_file) if oracle_file else None,
                        "success": success,
                        "failure_category": category,
                    }
                    attempt_file = output / "tasks" / task["task_id"] / f"attempt-{attempt}.json"
                    _atomic_write(
                        attempt_file,
                        (json.dumps(attempt_body, sort_keys=True) + "\n").encode("utf-8"),
                    )
                    attempts.append(attempt_body)
                    attempt_file_hashes.append(_prefixed_sha256(attempt_file))
                    final_source, final_result, final_error = source, result, extraction_error
                    if result is not None and result.get("status") == "ok":
                        break
                    if attempt >= roster["generation"]["max_repair_cycles"]:
                        break
                    messages.extend(
                        [
                            {"role": "assistant", "content": response["text"]},
                            {
                                "role": "user",
                                "content": (
                                    "The previous candidate was rejected. Repair it using only "
                                    "the diagnostics below. Return one complete Metis 0.43 source "
                                    "and nothing else.\n\nDiagnostics:\n"
                                    + _diagnostics(result, extraction_error)
                                ),
                            },
                        ]
                    )
                success, category, details = _score(
                    task, frozen, final_source, final_result, final_error
                )
                observations.append(
                    {
                        "task_id": task["task_id"],
                        "family": task["family"],
                        "parent_template_group": task["parent_template_group"],
                        "first_shot_success": first_shot,
                        "post_repair_success": success,
                        "attempt_count": len(attempts),
                        "failure_category": category,
                        "accepted_invented_identifiers": 0,
                        "semantic_details": details,
                        "final_source_sha256": (
                            _canonical_hash(final_source) if final_source else None
                        ),
                        "attempt_sha256": attempt_file_hashes,
                    }
                )
        finally:
            if worker.stdin is not None:
                with contextlib.suppress(BrokenPipeError):
                    worker.stdin.close()
            try:
                worker.wait(timeout=30)
            except subprocess.TimeoutExpired:
                _terminate_process_group(worker)
    if worker.returncode != 0:
        _fail(f"B12 worker failed with exit {worker.returncode}")
    if stderr_path.stat().st_size > 128 * 1024:
        _fail("B12 worker stderr exceeds the retained byte cap")
    after_project = _git_identity(PROJECT_ROOT)
    after_metis = _git_identity(metis_root)
    critical: list[str] = []
    if before_project != after_project or before_metis != after_metis:
        critical.append("repository_identity_drift")
    semantic = sum(row["post_repair_success"] for row in observations)
    invented = sum(row["accepted_invented_identifiers"] for row in observations)
    failures: dict[str, set[str]] = defaultdict(set)
    for row in observations:
        if row["failure_category"]:
            failures[row["failure_category"]].add(row["parent_template_group"])
    counts = {
        "in": 12,
        "out": len(observations),
        "distinct": len({row["task_id"] for row in observations}),
        "gaps": 12 - len(observations),
        "semantic_correct": semantic,
        "semantic_incorrect": 12 - semantic,
        "family_semantic_correct": {
            family: sum(
                row["post_repair_success"] for row in observations if row["family"] == family
            )
            for family in FAMILIES
        },
    }
    if counts["out"] != 12 or counts["distinct"] != 12 or counts["gaps"] != 0:
        critical.append("b12_roster_gap")
    if semantic < baseline["counts"]["semantic_correct"] or critical or invented:
        verdict = "STOP_B12_REGRESSION"
    elif (
        selection["selected_semantic_correct"] > selection["base_semantic_correct"]
        or semantic > baseline["counts"]["semantic_correct"]
    ):
        verdict = "LOCAL_ADAPTER_UPLIFT"
    else:
        verdict = "LOCAL_ADAPTER_EXPERIMENTAL"
    evidence_files = _evidence_records(output)
    evidence = {
        "files": evidence_files,
        "roster_sha256": _canonical_hash(evidence_files),
    }
    body = {
        "schema_version": 1,
        "status": "verified",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "mode": "adapter_on_b12_terminal_replay",
        "training_authorized": False,
        "selection_feedback": False,
        "verdict": verdict,
        "counts": counts,
        "baseline": {
            "id": "B12-v4",
            "file_sha256": BASELINE_FILE_SHA256,
            "report_sha256": BASELINE_REPORT_SHA256,
            "semantic_correct": baseline["counts"]["semantic_correct"],
        },
        "selection_receipt_sha256": _prefixed_sha256(selection_receipt),
        "adapter_off_restore_receipt_sha256": _prefixed_sha256(restore_receipt),
        "adapter_off_restore_self_sha256": restore["restore_sha256"],
        "dataset_receipt_sha256": selection["dataset_receipt_sha256"],
        "adapter": {
            "global_step": selection["selected_step"],
            "manifest_sha256": selection["checkpoint_manifest_sha256"],
            "adapter_sha256": selection["adapter_sha256"],
        },
        "identity": {
            "roster_file_sha256": ROSTER_FILE_SHA256,
            "freeze_file_sha256": FREEZE_FILE_SHA256,
            "freeze_sha256": FREEZE_SHA256,
            "oracle_runner_sha256": _prefixed_sha256(RUNNER_PATH),
            "project_before": before_project,
            "project_after": after_project,
            "metis_before": before_metis,
            "metis_after": after_metis,
        },
        "runtime": {"peak_metal_gb": peak_metal, "network": "sandbox_denied"},
        "critical_failures": critical,
        "accepted_invented_identifiers": invented,
        "recurring_failure_categories": sorted(
            category for category, groups in failures.items() if len(groups) >= 2
        ),
        "observations": observations,
        "raw_evidence": evidence,
    }
    receipt = {**body, "receipt_sha256": _canonical_hash(body)}
    _atomic_write(
        output / "receipt.json",
        (json.dumps(receipt, allow_nan=False, sort_keys=True) + "\n").encode("utf-8"),
    )
    return receipt


def verify_terminal_evidence(
    receipt_path: Path,
    *,
    adapter: Path,
    selection_receipt: Path,
    dataset_receipt: Path = DEFAULT_DATASET_RECEIPT,
    restore_receipt: Path = DEFAULT_RESTORE_RECEIPT,
) -> dict[str, Any]:
    """Replay the retained B12 attempt/oracle tree without invoking the model."""
    if receipt_path.resolve() != (DEFAULT_OUTPUT / "receipt.json").resolve():
        _fail("B12 receipt is not at the fixed terminal path")
    roster, freeze, baseline = _load_contracts(DEFAULT_ROSTER, DEFAULT_FREEZE, DEFAULT_BASELINE)
    selection = _selection(selection_receipt, adapter, dataset_receipt)
    try:
        restore = verify_adapter_off_restore_receipt(
            restore_receipt,
            adapter=adapter,
            dataset_receipt=dataset_receipt,
            selection_receipt=selection_receipt,
        )
    except RuntimeContractError as error:
        _fail(f"adapter-off restore receipt failed strict verification: {error}")
    value = _json(receipt_path)
    body = {key: item for key, item in value.items() if key != "receipt_sha256"}
    raw_evidence = value.get("raw_evidence")
    actual_files = _evidence_records(receipt_path.parent)
    if (
        value.get("receipt_sha256") != _canonical_hash(body)
        or value.get("schema_version") != 1
        or value.get("status") != "verified"
        or value.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or value.get("mode") != "adapter_on_b12_terminal_replay"
        or value.get("training_authorized") is not False
        or value.get("selection_feedback") is not False
        or value.get("selection_receipt_sha256") != _prefixed_sha256(selection_receipt)
        or value.get("dataset_receipt_sha256") != selection["dataset_receipt_sha256"]
        or value.get("adapter_off_restore_receipt_sha256") != _prefixed_sha256(restore_receipt)
        or value.get("adapter_off_restore_self_sha256") != restore["restore_sha256"]
        or not isinstance(raw_evidence, Mapping)
        or raw_evidence.get("files") != actual_files
        or raw_evidence.get("roster_sha256") != _canonical_hash(actual_files)
    ):
        _fail("B12 terminal receipt or raw evidence roster drift")
    observations = value.get("observations")
    if not isinstance(observations, list) or len(observations) != 12:
        _fail("B12 observation denominator drift")
    frozen_by_id = {item["task_id"]: item for item in freeze["tasks"]}
    expected_paths = {"worker.stderr.log"}
    recomputed: list[dict[str, Any]] = []
    peak_metal = 0.0
    for task, observed in zip(roster["tasks"], observations, strict=True):
        if not isinstance(observed, Mapping) or observed.get("task_id") != task["task_id"]:
            _fail("B12 observation order differs from the frozen roster")
        count = observed.get("attempt_count")
        if (
            type(count) is not int
            or not 1 <= count <= roster["generation"]["max_repair_cycles"] + 1
        ):
            _fail("B12 attempt count is invalid")
        frozen = frozen_by_id[task["task_id"]]
        messages = [{"role": "user", "content": frozen["initial_prompt"]}]
        attempt_hashes: list[str] = []
        first_shot = False
        final_source: str | None = None
        final_result: Mapping[str, Any] | None = None
        final_error: str | None = None
        for attempt in range(count):
            base = f"tasks/{task['task_id']}"
            response_name = f"{base}/response-{attempt}.json"
            attempt_name = f"{base}/attempt-{attempt}.json"
            expected_paths.update((response_name, attempt_name))
            response_path = receipt_path.parent / response_name
            attempt_path = receipt_path.parent / attempt_name
            response = _json(response_path)
            peak = response.get("peak_metal_gb")
            if (
                set(response) != {"request_id", "text", "peak_metal_gb"}
                or response.get("request_id") != f"{task['task_id']}:{attempt}"
                or not isinstance(response.get("text"), str)
                or not response["text"]
                or type(peak) not in (int, float)
                or not math.isfinite(peak)
                or not 0 <= peak <= LIMITS["metal_gb"]
            ):
                _fail("retained B12 response is malformed")
            peak_metal = max(peak_metal, float(peak))
            source, extraction_error = _extract_source(response["text"])
            result: Mapping[str, Any] | None = None
            oracle_path: Path | None = None
            if source is not None:
                oracle_name = f"{base}/oracle-{attempt}.json"
                expected_paths.add(oracle_name)
                oracle_path = receipt_path.parent / oracle_name
                envelope = _json(oracle_path)
                request = build_oracle_request(
                    source,
                    filename=task["filename"],
                    execution_mode="endpoint",
                    endpoint=task["endpoint"],
                    workspace_sources=task["workspace_sources"],
                )
                try:
                    verify_oracle_envelope(envelope, request=request)
                except Exception as error:  # noqa: BLE001
                    _fail(f"retained B12 oracle envelope is invalid: {type(error).__name__}")
                result = envelope.get("result")
            success, category, _details = _score(task, frozen, source, result, extraction_error)
            if attempt == 0:
                first_shot = success
            attempt_value = _json(attempt_path)
            if attempt_value != {
                "schema_version": 1,
                "task_id": task["task_id"],
                "attempt": attempt,
                "messages_sha256": _canonical_hash(messages),
                "response_sha256": _prefixed_sha256(response_path),
                "source_sha256": _canonical_hash(source) if source else None,
                "oracle_sha256": _prefixed_sha256(oracle_path) if oracle_path else None,
                "success": success,
                "failure_category": category,
            }:
                _fail("retained B12 attempt does not replay exactly")
            attempt_hashes.append(_prefixed_sha256(attempt_path))
            final_source, final_result, final_error = source, result, extraction_error
            if attempt + 1 < count:
                if result is not None and result.get("status") == "ok":
                    _fail("B12 retained an attempt after a successful compiler result")
                messages.extend(
                    [
                        {"role": "assistant", "content": response["text"]},
                        {
                            "role": "user",
                            "content": (
                                "The previous candidate was rejected. Repair it using only "
                                "the diagnostics below. Return one complete Metis 0.43 source "
                                "and nothing else.\n\nDiagnostics:\n"
                                + _diagnostics(result, extraction_error)
                            ),
                        },
                    ]
                )
        success, category, details = _score(task, frozen, final_source, final_result, final_error)
        recomputed_row = {
            "task_id": task["task_id"],
            "family": task["family"],
            "parent_template_group": task["parent_template_group"],
            "first_shot_success": first_shot,
            "post_repair_success": success,
            "attempt_count": count,
            "failure_category": category,
            "accepted_invented_identifiers": 0,
            "semantic_details": details,
            "final_source_sha256": _canonical_hash(final_source) if final_source else None,
            "attempt_sha256": attempt_hashes,
        }
        if dict(observed) != recomputed_row:
            _fail("B12 observation differs from replayed raw evidence")
        recomputed.append(recomputed_row)
    if set(actual_files) != expected_paths:
        _fail("B12 raw evidence contains an extra or missing task artifact")
    stderr = receipt_path.parent / "worker.stderr.log"
    if stderr.stat().st_size > 128 * 1024:
        _fail("B12 retained stderr exceeds its cap")
    semantic = sum(row["post_repair_success"] for row in recomputed)
    invented = sum(row["accepted_invented_identifiers"] for row in recomputed)
    failures: dict[str, set[str]] = defaultdict(set)
    for row in recomputed:
        if row["failure_category"]:
            failures[row["failure_category"]].add(row["parent_template_group"])
    recurring = sorted(category for category, groups in failures.items() if len(groups) >= 2)
    identity = value.get("identity")
    critical = value.get("critical_failures")
    if not isinstance(identity, Mapping) or not isinstance(critical, list):
        _fail("B12 identity or critical veto roster is malformed")
    verdict = (
        "STOP_B12_REGRESSION"
        if semantic < baseline["counts"]["semantic_correct"] or critical or invented
        else "LOCAL_ADAPTER_UPLIFT"
        if selection["selected_semantic_correct"] > selection["base_semantic_correct"]
        or semantic > baseline["counts"]["semantic_correct"]
        else "LOCAL_ADAPTER_EXPERIMENTAL"
    )
    if (
        value.get("verdict") != verdict
        or value.get("counts", {}).get("semantic_correct") != semantic
        or value.get("accepted_invented_identifiers") != invented
        or value.get("recurring_failure_categories") != recurring
        or value.get("runtime", {}).get("peak_metal_gb") != peak_metal
        or identity.get("project_before") != identity.get("project_after")
        or identity.get("metis_before") != identity.get("metis_after")
    ):
        _fail("B12 verdict or terminal aggregate does not replay")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--selection-receipt", type=Path, required=True)
    parser.add_argument("--dataset-receipt", type=Path, default=DEFAULT_DATASET_RECEIPT)
    parser.add_argument("--restore-receipt", type=Path, default=DEFAULT_RESTORE_RECEIPT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--metis-root", type=Path, default=DEFAULT_METIS_ROOT)
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--worker-python", type=Path, default=DEFAULT_WORKER_PYTHON)
    parser.add_argument("--timeout", type=float, default=LIMITS["hours"] * 3600)
    args = parser.parse_args(argv)
    try:
        result = replay_b12(
            adapter=args.adapter,
            selection_receipt=args.selection_receipt,
            dataset_receipt=args.dataset_receipt,
            restore_receipt=args.restore_receipt,
            model=args.model,
            metis_root=args.metis_root,
            roster_path=args.roster,
            freeze_path=args.freeze,
            baseline_path=args.baseline,
            output=args.output,
            worker_python=args.worker_python,
            timeout=args.timeout,
        )
    except B12ReplayError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
