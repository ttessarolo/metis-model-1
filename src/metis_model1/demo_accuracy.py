"""Fresh, paired accuracy gate for the macOS Metis Model 1 demo.

The gate is deliberately smaller than the global Accuracy-99 contract.  It
freezes twelve public-synthetic tasks before inference, runs the pinned base
and selected adapter with identical deterministic settings, and scores source
outputs through the pinned catalog ``describe`` implementation.  Raw model
outputs stay under ignored ``artifacts/`` and are never training data.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from metis_model1 import catalog_maintenance_pin as catalog_pin
from metis_model1 import initial_local_qlora_runtime as qlora
from metis_model1.catalog_maintenance_probe import (
    _describe_source_in_snapshot,
    _extract_source,
)
from metis_model1.catalog_retrieval_refresh import _pinned_snapshot

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASKS_PATH = PROJECT_ROOT / "fixtures/demo-accuracy-v1/tasks.json"
TRUTH_PATH = PROJECT_ROOT / "manifests/demo-accuracy-truth-v1.json"
FREEZE_PATH = PROJECT_ROOT / "manifests/demo-accuracy-freeze-v1.json"
EVIDENCE_PATH = PROJECT_ROOT / "manifests/demo-accuracy-evaluation-v1.json"
RUN_DIR = PROJECT_ROOT / "artifacts/demo-accuracy-v1"
ADAPTER_PATH = PROJECT_ROOT / "artifacts/initial-local-qlora-v1/run-v2/checkpoints/step-00000050"
SELECTION_PATH = PROJECT_ROOT / "artifacts/initial-local-qlora-v1/run-v2/selection.json"
DATASET_TRAIN = PROJECT_ROOT / "artifacts/initial-local-qlora-v1/dataset/train.jsonl"
DATASET_DEV = PROJECT_ROOT / "artifacts/initial-local-qlora-v1/dataset/dev.jsonl"
B12_ROSTER = PROJECT_ROOT / "artifacts/w5-xs/2026-08-24-delivery/b12-roster-v2.json"
DEFAULT_METIS_ROOT = Path("/Users/tommasotessarolo/Developer/ares-matioska/metis")
DEFAULT_NODE = Path("/Users/tommasotessarolo/.local/bin/node")
QUALIFICATION_PYTHON = PROJECT_ROOT / "qualification/.venv/bin/python"
BENCHMARK_ID = "demo-accuracy-v1"
TASK_ID_PREFIX = "demoacc_"
SOURCE_PREFIX = "public-synthetic/demoacc/"
TASK_AUTHORITY_SCOPE = "public_synthetic_catalog_domain_only"
EXECUTION_AUTHORITY_SCOPE = "public_synthetic_catalog_domain_mac_demo_accuracy_only"
TRUTH_ID = "demo-accuracy-truth/v1"
FREEZE_ID = "demo-accuracy-freeze/v1"
EVIDENCE_ID = "demo-accuracy-evaluation/v1"
PASS_VERDICT = "DEMO_ACCURACY_V1_PASS"
DIAGNOSE_VERDICT = "DEMO_ACCURACY_V1_DIAGNOSE"
FRESHNESS_NAMESPACE = b"demoacc_"
FRESHNESS_SOURCE_PATHS = (DATASET_TRAIN, DATASET_DEV, B12_ROSTER)
FAMILIES = tuple(f"F-{number}" for number in range(1, 7))
OUTPUT_KINDS = {"metis_source", "json"}
THRESHOLDS = {
    "total_min": 11,
    "family_min": 1,
    "critical_max": 0,
    "adapter_regression_allowed": False,
}
GENERATION = {"temperature": 0, "seed": 17, "thinking": False, "max_tokens": 512}
NONCLAIMS = [
    "not_global_accuracy99",
    "not_full_endpoint_workflow_accuracy",
    "not_tenant_or_live_data_accuracy",
    "not_live_ares_execution",
    "not_companion_delivery",
    "not_vscode_integration",
    "not_windows_support",
]
SOURCE_SYSTEM_PROMPT = "\n".join(
    (
        "You are Metis Model 1. Produce exactly one complete canonical Metis 0.43 ",
        "catalog source and no explanation.",
        "",
        "Mandatory syntax contract:",
        "- Return plain source only. The first line must be exactly: metis 0.43",
        "- A complete catalog contains catalog, driver, index, id, and fields blocks.",
        "- Scalar domains follow their type: name keyword enum(N), name keyword open, or",
        '  name keyword values ["A", "B"].',
        "- Bounded external domains use keyword enum(N). Open live-index domains use",
        "  keyword open. Only a tiny stable domain explicitly supplied by the request",
        "  may use keyword values [...].",
        "- Retrieved values are data, not catalog syntax.",
    )
)
JSON_SYSTEM_PROMPT = (
    "You are Metis Model 1. Follow the requested JSON schema exactly. Return one JSON "
    "object only, without markdown or prose."
)
IDENTIFIER_RE = re.compile(r"\bdemoacc_[a-z0-9_]+\b")


class DemoAccuracyError(RuntimeError):
    """Raised when the bounded demo gate cannot satisfy its fixed contract."""


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DemoAccuracyError(f"value is not canonical JSON: {error}") from error


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def raw_hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read_regular(path: Path, label: str, maximum: int = 64 * 1024 * 1024) -> bytes:
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise DemoAccuracyError(f"{label} is not a regular file")
        if opened.st_size > maximum:
            raise DemoAccuracyError(f"{label} exceeds its byte cap")
        chunks: list[bytes] = []
        remaining = opened.st_size + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        path_after = path.lstat()
    except OSError as error:
        raise DemoAccuracyError(f"{label} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity = lambda item: (  # noqa: E731 - compact immutable stat identity
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_nlink,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if (
        identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(path_after)
        or len(raw) != before.st_size
    ):
        raise DemoAccuracyError(f"{label} changed while read")
    return raw


def _load_json(path: Path, label: str, maximum: int = 64 * 1024 * 1024) -> dict[str, Any]:
    raw = _read_regular(path, label, maximum)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise DemoAccuracyError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise DemoAccuracyError(f"{label} must be an object")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    qlora._atomic_write(path, canonical_bytes(value) + b"\n")


def _task_keys(task: Mapping[str, Any]) -> set[str]:
    base = {"task_id", "family", "source", "output_kind", "prompt"}
    if "input_source" in task:
        base.add("input_source")
    base.add("expected_source" if task.get("output_kind") == "metis_source" else "expected_json")
    return base


def validate_tasks(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    if set(manifest) != {
        "schema_version",
        "benchmark_id",
        "status",
        "authority_scope",
        "model_outputs_observed",
        "generation",
        "thresholds",
        "tasks",
    }:
        raise DemoAccuracyError("task manifest keys differ from the fixed contract")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("benchmark_id") != BENCHMARK_ID
        or manifest.get("status") != "pre_output"
        or manifest.get("authority_scope") != TASK_AUTHORITY_SCOPE
        or manifest.get("model_outputs_observed") is not False
        or manifest.get("generation") != GENERATION
        or manifest.get("thresholds") != THRESHOLDS
    ):
        raise DemoAccuracyError("task manifest header differs from the fixed contract")
    raw_tasks = manifest.get("tasks")
    if not isinstance(raw_tasks, list) or len(raw_tasks) != 12:
        raise DemoAccuracyError("task manifest must contain exactly twelve tasks")
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict) or set(raw_task) != _task_keys(raw_task):
            raise DemoAccuracyError("task fields differ from the fixed contract")
        task_id = raw_task.get("task_id")
        family = raw_task.get("family")
        output_kind = raw_task.get("output_kind")
        if (
            not isinstance(task_id, str)
            or not task_id.startswith(TASK_ID_PREFIX)
            or task_id in seen
            or family not in FAMILIES
            or output_kind not in OUTPUT_KINDS
            or not isinstance(raw_task.get("source"), str)
            or not raw_task["source"].startswith(SOURCE_PREFIX)
            or not isinstance(raw_task.get("prompt"), str)
            or not raw_task["prompt"]
        ):
            raise DemoAccuracyError("task identity or provenance is invalid")
        seen.add(task_id)
        if "input_source" in raw_task:
            value = raw_task["input_source"]
            if not isinstance(value, str) or "catalog public.video" not in value:
                raise DemoAccuracyError(f"task input is not a public.video source: {task_id}")
        if output_kind == "metis_source":
            target = raw_task.get("expected_source")
            if not isinstance(target, str) or "catalog public.video" not in target:
                raise DemoAccuracyError(f"source target is invalid: {task_id}")
        elif not isinstance(raw_task.get("expected_json"), dict):
            raise DemoAccuracyError(f"JSON target is invalid: {task_id}")
        tasks.append(dict(raw_task))
    if Counter(task["family"] for task in tasks) != Counter({family: 2 for family in FAMILIES}):
        raise DemoAccuracyError("task family census must be exactly two per F-1 through F-6")
    if Counter(task["output_kind"] for task in tasks) != Counter({"metis_source": 8, "json": 4}):
        raise DemoAccuracyError("task output-kind census must be eight source and four JSON")
    return tasks


def load_tasks() -> tuple[dict[str, Any], list[dict[str, Any]], bytes]:
    raw = _read_regular(TASKS_PATH, "demo accuracy tasks")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DemoAccuracyError("demo accuracy tasks are not valid JSON") from error
    if not isinstance(manifest, dict):
        raise DemoAccuracyError("demo accuracy task manifest must be an object")
    return manifest, validate_tasks(manifest), raw


def build_messages(task: Mapping[str, Any]) -> list[dict[str, str]]:
    prompt = str(task["prompt"])
    before = task.get("input_source")
    if before is not None:
        prompt += "\n\nCurrent source:\n" + str(before).rstrip()
    system = SOURCE_SYSTEM_PROMPT if task["output_kind"] == "metis_source" else JSON_SYSTEM_PROMPT
    return [{"role": "system", "content": system}, {"role": "user", "content": prompt}]


def _source_record(path: Path, label: str) -> dict[str, Any]:
    raw = _read_regular(path, label, 512 * 1024 * 1024)
    return {"path": str(path.relative_to(PROJECT_ROOT)), "bytes": len(raw), "sha256": raw_hash(raw)}


def _freshness_records(tasks_raw: bytes, tasks: list[Mapping[str, Any]]) -> dict[str, Any]:
    records = [
        _source_record(path, f"freshness source {path.name}") for path in FRESHNESS_SOURCE_PATHS
    ]
    source_raw = b"\n".join(
        _read_regular(PROJECT_ROOT / record["path"], record["path"], 512 * 1024 * 1024)
        for record in records
    )
    task_ids = [str(task["task_id"]) for task in tasks]
    if (
        any(task_id.encode() in source_raw for task_id in task_ids)
        or FRESHNESS_NAMESPACE in source_raw
    ):
        raise DemoAccuracyError("demo task namespace is not fresh against consumed local rosters")
    if FRESHNESS_NAMESPACE not in tasks_raw:
        raise DemoAccuracyError("demo task namespace is absent")
    return {
        "method": "exact_task_id_and_reserved_namespace_scan",
        "sources": records,
        "task_id_hits": 0,
        "reserved_namespace_hits": 0,
        "limits": "not_semantic_template_independence",
    }


def build_truth(metis_root: Path, node_path: Path) -> dict[str, Any]:
    manifest, tasks, tasks_raw = load_tasks()
    pin_report = catalog_pin.verify_catalog_maintenance_pin(metis_root, node_path)
    if pin_report.get("status") != "verified_local_cooperative":
        raise DemoAccuracyError("catalog maintenance pin is not locally verified")
    truth_tasks: list[dict[str, Any]] = []
    with _pinned_snapshot(metis_root, node_path) as snapshot:
        for task in tasks:
            messages = build_messages(task)
            target: dict[str, Any]
            if task["output_kind"] == "metis_source":
                normalized, receipt = _describe_source_in_snapshot(
                    snapshot, str(task["expected_source"])
                )
                target = {
                    "kind": "metis_source",
                    "normalized": normalized,
                    "normalized_sha256": canonical_hash(normalized),
                    "describe_receipt_sha256": receipt["receipt_sha256"],
                }
            else:
                expected = task["expected_json"]
                target = {
                    "kind": "json",
                    "normalized": expected,
                    "normalized_sha256": canonical_hash(expected),
                }
            truth_tasks.append(
                {
                    "task_id": task["task_id"],
                    "family": task["family"],
                    "output_kind": task["output_kind"],
                    "messages_sha256": canonical_hash(messages),
                    "target": target,
                    "model_output_observed": False,
                }
            )
    pin_manifest = catalog_pin.load_catalog_maintenance_pin(PROJECT_ROOT)
    body: dict[str, Any] = {
        "schema_version": 1,
        "truth_id": TRUTH_ID,
        "status": "truth_fixed_before_model_output",
        "authority_scope": manifest["authority_scope"],
        "tasks_file_sha256": raw_hash(tasks_raw),
        "catalog_pin": {
            "revision": pin_manifest["revision"],
            "tree": pin_manifest["tree"],
            "manifest_sha256": catalog_pin.manifest_sha256(pin_manifest),
            "verification": pin_report["status"],
        },
        "freshness": _freshness_records(tasks_raw, tasks),
        "counts": {
            "tasks_in": 12,
            "tasks_out": 12,
            "tasks_distinct": 12,
            "gaps": 0,
            "families": {family: 2 for family in FAMILIES},
        },
        "tasks": truth_tasks,
        "generation": GENERATION,
        "thresholds": THRESHOLDS,
        "model_outputs_observed": False,
        "training_input_allowed": False,
        "nonclaims": NONCLAIMS,
    }
    body["truth_sha256"] = canonical_hash(body)
    return body


def truth(args: argparse.Namespace) -> int:
    if TRUTH_PATH.exists() or TRUTH_PATH.is_symlink():
        raise DemoAccuracyError(f"truth output already exists: {TRUTH_PATH}")
    body = build_truth(Path(args.metis_root), Path(args.node_path))
    _atomic_json(TRUTH_PATH, body)
    print(
        json.dumps(
            {
                "event": "demo_accuracy_truth",
                "tasks": 12,
                "truth_sha256": body["truth_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


def _git(*args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(PROJECT_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_OPTIONAL_LOCKS": "0",
        },
    )
    if check and completed.returncode != 0:
        raise DemoAccuracyError(f"Git command failed: {' '.join(args)}")
    return completed.stdout.strip()


def _remote_ref(remote: str) -> str:
    branch = _git("symbolic-ref", "--short", "HEAD")
    if not branch.startswith("codex/"):
        raise DemoAccuracyError("demo accuracy requires a codex/* branch")
    return f"refs/heads/{branch}"


def _require_published(remote: str, remote_ref: str) -> tuple[str, str]:
    head = _git("rev-parse", "HEAD")
    rows = _git("ls-remote", remote, remote_ref).splitlines()
    if len(rows) != 1 or rows[0].split() != [head, remote_ref]:
        raise DemoAccuracyError("current HEAD is not exactly published")
    return head, _git("rev-parse", "HEAD^{tree}")


def _tracked_record(relative: str) -> dict[str, Any]:
    raw = subprocess.check_output(
        ["/usr/bin/git", "-C", str(PROJECT_ROOT), "show", f"HEAD:{relative}"], timeout=60
    )
    tree = _git("ls-tree", "HEAD", "--", relative).split()
    if len(tree) != 4 or tree[1] != "blob" or tree[3] != relative:
        raise DemoAccuracyError(f"bound input is not one committed blob: {relative}")
    current = _read_regular(PROJECT_ROOT / relative, f"bound input {relative}")
    if current != raw:
        raise DemoAccuracyError(f"bound input differs from HEAD: {relative}")
    return {
        "path": relative,
        "bytes": len(raw),
        "sha256": raw_hash(raw),
        "git_blob_oid": tree[2],
    }


BOUND_PATHS = (
    "fixtures/demo-accuracy-v1/tasks.json",
    "manifests/demo-accuracy-truth-v1.json",
    "src/metis_model1/demo_accuracy.py",
    "src/metis_model1/initial_local_qlora_runtime.py",
    "src/metis_model1/catalog_maintenance_probe.py",
    "src/metis_model1/catalog_maintenance_pin.py",
    "src/metis_model1/catalog_retrieval.py",
    "src/metis_model1/catalog_retrieval_refresh.py",
    "src/metis_model1/oracles.py",
    "tests/test_demo_accuracy.py",
    "docs/20-demo-accuracy-closure.md",
    "qualification/checkpoint-pin.json",
    "qualification/runtime-pin.json",
    "qualification/uv.lock",
    "manifests/catalog-maintenance-pin-v1.json",
    "manifests/catalog-retrieval-public-synthetic-v1.json",
    "manifests/catalog-retrieval-execution-v1.json",
    "schemas/catalog-maintenance-pin.schema.json",
    "schemas/catalog-retrieval-execution-receipt.schema.json",
    "fixtures/catalog-maintenance/public-synthetic-v1/metis.toml",
    "fixtures/catalog-maintenance/public-synthetic-v1/catalogs/aa-video.metis",
    "fixtures/catalog-maintenance/public-synthetic-v1/catalogs/bb-people.metis",
    "fixtures/catalog-maintenance/public-synthetic-v1/values/aa-list.metis",
    "fixtures/catalog-maintenance/public-synthetic-v1/values/bb-reflected.metis",
    "fixtures/catalog-maintenance/public-synthetic-v1/values/cc-editorial.metis",
)


def _selection_identity() -> dict[str, Any]:
    value = _load_json(SELECTION_PATH, "adapter selection receipt")
    if value.get("selected_step") != 50:
        raise DemoAccuracyError("selected adapter is not step 50")
    checkpoint = qlora.verify_checkpoint(ADAPTER_PATH)
    adapter_hash = "sha256:" + checkpoint["file_records"]["adapters.safetensors"]["sha256"]
    if value.get("adapter_sha256") != adapter_hash:
        raise DemoAccuracyError("selection receipt does not bind the step-50 adapter")
    return {
        "selection": _source_record(SELECTION_PATH, "adapter selection receipt"),
        "selected_step": 50,
        "adapter_sha256": adapter_hash,
        "checkpoint": checkpoint,
    }


def _validate_self_hash(value: Mapping[str, Any], field: str) -> None:
    observed = value.get(field)
    body = {key: item for key, item in value.items() if key != field}
    if observed != canonical_hash(body):
        raise DemoAccuracyError(f"{field} does not match its canonical body")


def _verify_truth_against_pinned_inputs(
    value: Mapping[str, Any], metis_root: Path, node_path: Path
) -> None:
    _validate_self_hash(value, "truth_sha256")
    rebuilt = build_truth(metis_root, node_path)
    if value != rebuilt:
        raise DemoAccuracyError("truth differs from a fresh pinned-oracle reconstruction")


def build_freeze(remote: str, metis_root: Path, node_path: Path) -> dict[str, Any]:
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise DemoAccuracyError("tracked/untracked worktree must be clean before freeze")
    remote_ref = _remote_ref(remote)
    head, tree = _require_published(remote, remote_ref)
    truth_value = _load_json(TRUTH_PATH, "demo accuracy truth")
    _verify_truth_against_pinned_inputs(truth_value, metis_root, node_path)
    _, tasks, tasks_raw = load_tasks()
    if truth_value.get("tasks_file_sha256") != raw_hash(tasks_raw):
        raise DemoAccuracyError("truth does not bind the current task manifest")
    bound = [_tracked_record(relative) for relative in BOUND_PATHS]
    runtime = qlora._check_runtime()
    identities = {
        "base": qlora.evaluation_identity(qlora.BASE_CHECKPOINT, None),
        "adapter": qlora.evaluation_identity(qlora.BASE_CHECKPOINT, ADAPTER_PATH),
        "selection": _selection_identity(),
    }
    _assert_artifact_root()
    if RUN_DIR.exists() or RUN_DIR.is_symlink():
        raise DemoAccuracyError(f"fixed run directory already exists: {RUN_DIR}")
    body: dict[str, Any] = {
        "schema_version": 1,
        "freeze_id": FREEZE_ID,
        "status": "frozen_before_model_output",
        "authority_scope": EXECUTION_AUTHORITY_SCOPE,
        "preimage_commit": head,
        "preimage_tree": tree,
        "remote": remote,
        "remote_ref": remote_ref,
        "bound_inputs": bound,
        "truth_sha256": truth_value["truth_sha256"],
        "tasks_file_sha256": raw_hash(tasks_raw),
        "runtime": runtime,
        "identities": identities,
        "sandbox_policy_sha256": canonical_hash(qlora.EVALUATION_SANDBOX_POLICY),
        "generation": GENERATION,
        "thresholds": THRESHOLDS,
        "counts": {
            "tasks_in": len(tasks),
            "tasks_out": len(tasks),
            "tasks_distinct": len({task["task_id"] for task in tasks}),
            "gaps": 0,
            "families": {family: 2 for family in FAMILIES},
        },
        "run_dir": str(RUN_DIR.relative_to(PROJECT_ROOT)),
        "model_outputs_observed": False,
        "training_authorized": False,
        "nonclaims": NONCLAIMS,
    }
    body["freeze_sha256"] = canonical_hash(body)
    return body


def freeze(args: argparse.Namespace) -> int:
    if FREEZE_PATH.exists() or FREEZE_PATH.is_symlink():
        raise DemoAccuracyError(f"freeze output already exists: {FREEZE_PATH}")
    body = build_freeze(args.remote, Path(args.metis_root), Path(args.node_path))
    _atomic_json(FREEZE_PATH, body)
    print(
        json.dumps(
            {
                "event": "demo_accuracy_freeze",
                "freeze_sha256": body["freeze_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


def _extract_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    stripped = text.strip()
    if stripped.startswith("```"):
        matches = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
        if matches is None:
            return None, "invalid_json_fence"
        stripped = matches.group(1).strip()
    try:
        value = json.loads(
            stripped,
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
    except (ValueError, json.JSONDecodeError):
        return None, "invalid_json"
    if not isinstance(value, dict):
        return None, "json_object_required"
    return value, None


def _invented_identifiers(candidate: str, expected: str) -> list[str]:
    return sorted(set(IDENTIFIER_RE.findall(candidate)) - set(IDENTIFIER_RE.findall(expected)))


def score_candidate(
    task: Mapping[str, Any],
    response: Mapping[str, Any],
    truth_task: Mapping[str, Any],
    normalizer: Callable[[str], tuple[dict[str, Any], dict[str, Any]]] | None,
) -> dict[str, Any]:
    text = response.get("text")
    if not isinstance(text, str) or not text:
        raise DemoAccuracyError("worker returned an empty candidate")
    expected_hash = truth_task["target"]["normalized_sha256"]
    failure_code: str | None = None
    normalized_hash: str | None = None
    invented: list[str] = []
    if task["output_kind"] == "metis_source":
        source, failure_code = _extract_source(text)
        if source is not None:
            invented = _invented_identifiers(source, str(task["expected_source"]))
            if normalizer is None:
                raise DemoAccuracyError("source task has no catalog normalizer")
            try:
                normalized, _receipt = normalizer(source)
                normalized_hash = canonical_hash(normalized)
            except Exception:  # noqa: BLE001 - candidate error is intentionally redacted
                failure_code = "catalog_describe_rejected_candidate"
    else:
        normalized, failure_code = _extract_json(text)
        if normalized is not None:
            normalized_hash = canonical_hash(normalized)
    semantic_correct = normalized_hash == expected_hash and not invented
    critical = failure_code is not None
    if not semantic_correct and failure_code is None:
        failure_code = "semantic_mismatch"
    return {
        "task_id": task["task_id"],
        "family": task["family"],
        "output_kind": task["output_kind"],
        "semantic_correct": semantic_correct,
        "critical_failure": critical,
        "failure_code": failure_code,
        "invented_identifiers": invented,
        "candidate_sha256": raw_hash(text.encode("utf-8")),
        "normalized_sha256": normalized_hash,
        "expected_normalized_sha256": expected_hash,
        "peak_metal_gb": response["peak_metal_gb"],
    }


def summarize(observations: list[Mapping[str, Any]]) -> dict[str, Any]:
    task_ids = [str(item["task_id"]) for item in observations]
    family = {
        name: sum(bool(item["semantic_correct"]) for item in observations if item["family"] == name)
        for name in FAMILIES
    }
    return {
        "tasks_in": 12,
        "tasks_out": len(observations),
        "tasks_distinct": len(set(task_ids)),
        "gaps": 12 - len(observations),
        "semantic_correct": sum(bool(item["semantic_correct"]) for item in observations),
        "critical_failure": sum(bool(item["critical_failure"]) for item in observations),
        "invented_identifiers": sum(bool(item["invented_identifiers"]) for item in observations),
        "family": family,
        "peak_metal_gb": max(float(item["peak_metal_gb"]) for item in observations),
    }


def gate_arithmetic(
    base: list[Mapping[str, Any]], adapter: list[Mapping[str, Any]]
) -> dict[str, Any]:
    if len(base) != 12 or len(adapter) != 12:
        raise DemoAccuracyError("paired gate requires twelve base and twelve adapter observations")
    if [item["task_id"] for item in base] != [item["task_id"] for item in adapter]:
        raise DemoAccuracyError("base/adapter roster order differs")
    base_counts = summarize(base)
    adapter_counts = summarize(adapter)
    paired_regressions = [
        str(left["task_id"])
        for left, right in zip(base, adapter, strict=True)
        if left["semantic_correct"] and not right["semantic_correct"]
    ]
    gates = {
        "adapter_total": adapter_counts["semantic_correct"] >= THRESHOLDS["total_min"],
        "family_floor": all(
            count >= THRESHOLDS["family_min"] for count in adapter_counts["family"].values()
        ),
        "critical_zero": adapter_counts["critical_failure"] <= THRESHOLDS["critical_max"],
        "invented_zero": adapter_counts["invented_identifiers"] == 0,
        "roster_complete": adapter_counts["gaps"] == 0 and adapter_counts["tasks_distinct"] == 12,
        "aggregate_no_regression": adapter_counts["semantic_correct"]
        >= base_counts["semantic_correct"],
        "paired_no_regression": not paired_regressions,
    }
    genuine_failures = [
        item
        for item in adapter
        if not item["semantic_correct"]
        and not item["critical_failure"]
        and item["failure_code"] == "semantic_mismatch"
    ]
    failure_families = sorted({str(item["family"]) for item in genuine_failures})
    delta_threshold_met = len(genuine_failures) >= 3 and len(failure_families) >= 2
    passed = all(gates.values())
    return {
        "verdict": PASS_VERDICT if passed else DIAGNOSE_VERDICT,
        "base": base_counts,
        "adapter": adapter_counts,
        "gates": gates,
        "paired_regressions": paired_regressions,
        "delta_qlora": {
            "threshold_met": delta_threshold_met,
            "eligible": False,
            "adjudication_required": delta_threshold_met,
            "genuine_failure_count": len(genuine_failures),
            "families": failure_families,
            "action": "l0_oracle_adjudication" if delta_threshold_met else "no_retrain",
        },
    }


def _candidate_lines(tasks: list[Mapping[str, Any]], responses: list[Mapping[str, Any]]) -> bytes:
    return b"".join(
        canonical_bytes(
            {
                "task_id": task["task_id"],
                "text": response["text"],
                "peak_metal_gb": response["peak_metal_gb"],
            }
        )
        + b"\n"
        for task, response in zip(tasks, responses, strict=True)
    )


def _candidate_responses(path: Path, tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    raw = _read_regular(path, f"raw candidates {path.name}", 32 * 1024 * 1024)
    lines = raw.splitlines()
    if len(lines) != len(tasks):
        raise DemoAccuracyError("raw candidate count differs from the frozen roster")
    responses: list[dict[str, Any]] = []
    for task, line in zip(tasks, lines, strict=True):
        try:
            value = json.loads(
                line,
                parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
            )
        except (ValueError, json.JSONDecodeError) as error:
            raise DemoAccuracyError("raw candidate row is not valid JSON") from error
        peak = value.get("peak_metal_gb") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or set(value) != {"task_id", "text", "peak_metal_gb"}
            or value.get("task_id") != task["task_id"]
            or not isinstance(value.get("text"), str)
            or not value["text"]
            or type(peak) not in (int, float)
            or not 0 <= float(peak) <= qlora.LIMITS["metal_gb"]
        ):
            raise DemoAccuracyError("raw candidate row differs from the fixed contract")
        if line != canonical_bytes(value):
            raise DemoAccuracyError("raw candidate row is not canonical JSON")
        responses.append(
            {"request_id": task["task_id"], "text": value["text"], "peak_metal_gb": peak}
        )
    return responses


def _assert_artifact_root() -> Path:
    artifact_root = PROJECT_ROOT / "artifacts"
    if RUN_DIR.parent != artifact_root:
        raise DemoAccuracyError("fixed run directory escaped the artifact root")
    for path, label in ((PROJECT_ROOT, "project root"), (artifact_root, "artifact root")):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise DemoAccuracyError(f"{label} is not a direct directory")
    return artifact_root


def _assert_run_root() -> None:
    _assert_artifact_root()
    metadata = RUN_DIR.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise DemoAccuracyError("fixed run root is not a direct directory")


def _directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
    )


def _open_direct_directory(path: Path, label: str) -> tuple[int, tuple[int, ...]]:
    before = path.lstat()
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
    )
    opened = os.fstat(descriptor)
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISDIR(before.st_mode)
        or not stat.S_ISDIR(opened.st_mode)
        or _directory_identity(before) != _directory_identity(opened)
    ):
        os.close(descriptor)
        raise DemoAccuracyError(f"{label} is not a stable direct directory")
    return descriptor, _directory_identity(opened)


def _create_run_children() -> None:
    _assert_run_root()
    for label in ("base", "adapter"):
        child = RUN_DIR / label
        try:
            child.mkdir(mode=0o700, parents=False, exist_ok=False)
        except FileExistsError as error:
            raise DemoAccuracyError(f"run child already exists: {label}") from error
        descriptor, _identity = _open_direct_directory(child, f"run child {label}")
        os.close(descriptor)
    if {path.name for path in RUN_DIR.iterdir()} != {"base", "adapter"}:
        raise DemoAccuracyError("run child directory roster differs")


def _write_run_file(directory: Path, name: str, raw: bytes) -> Path:
    if directory not in {RUN_DIR, RUN_DIR / "base", RUN_DIR / "adapter"}:
        raise DemoAccuracyError("run file directory is outside the fixed roster")
    if name not in {"candidates.jsonl", "report.json"} or not raw:
        raise DemoAccuracyError("run file name or payload is invalid")
    _assert_run_root()
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
                raise DemoAccuracyError("run file write made no progress")
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
            raise DemoAccuracyError("published run file or directory identity changed")
    except OSError as error:
        raise DemoAccuracyError(f"cannot publish fixed run file {name}") from error
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if temporary_created:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=descriptor)
        os.close(descriptor)
    return directory / name


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


def _verify_bound_inputs(records: list[Mapping[str, Any]]) -> None:
    if [record["path"] for record in records] != list(BOUND_PATHS):
        raise DemoAccuracyError("freeze bound-input roster differs")
    for expected in records:
        if _tracked_record(str(expected["path"])) != expected:
            raise DemoAccuracyError(f"bound input changed: {expected['path']}")


def _verify_freeze_lineage(freeze_value: Mapping[str, Any], head: str) -> None:
    expected_keys = {
        "schema_version",
        "freeze_id",
        "status",
        "authority_scope",
        "preimage_commit",
        "preimage_tree",
        "remote",
        "remote_ref",
        "bound_inputs",
        "truth_sha256",
        "tasks_file_sha256",
        "runtime",
        "identities",
        "sandbox_policy_sha256",
        "generation",
        "thresholds",
        "counts",
        "run_dir",
        "model_outputs_observed",
        "training_authorized",
        "nonclaims",
        "freeze_sha256",
    }
    if (
        set(freeze_value) != expected_keys
        or freeze_value.get("schema_version") != 1
        or freeze_value.get("freeze_id") != FREEZE_ID
        or freeze_value.get("status") != "frozen_before_model_output"
        or freeze_value.get("authority_scope") != EXECUTION_AUTHORITY_SCOPE
        or freeze_value.get("run_dir") != str(RUN_DIR.relative_to(PROJECT_ROOT))
        or freeze_value.get("generation") != GENERATION
        or freeze_value.get("thresholds") != THRESHOLDS
        or freeze_value.get("counts")
        != {
            "tasks_in": 12,
            "tasks_out": 12,
            "tasks_distinct": 12,
            "gaps": 0,
            "families": {family: 2 for family in FAMILIES},
        }
        or freeze_value.get("sandbox_policy_sha256")
        != canonical_hash(qlora.EVALUATION_SANDBOX_POLICY)
        or freeze_value.get("nonclaims") != NONCLAIMS
        or freeze_value.get("model_outputs_observed") is not False
        or freeze_value.get("training_authorized") is not False
    ):
        raise DemoAccuracyError("freeze is not an executable pre-output seal")
    preimage = freeze_value.get("preimage_commit")
    preimage_tree = freeze_value.get("preimage_tree")
    if (
        not isinstance(preimage, str)
        or not isinstance(preimage_tree, str)
        or _git("rev-parse", f"{preimage}^{{tree}}") != preimage_tree
    ):
        raise DemoAccuracyError("freeze preimage commit/tree binding is invalid")
    ancestor = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(PROJECT_ROOT),
            "merge-base",
            "--is-ancestor",
            preimage,
            head,
        ],
        check=False,
    )
    if ancestor.returncode != 0:
        raise DemoAccuracyError("freeze preimage is not an ancestor of current HEAD")


def run(args: argparse.Namespace) -> int:
    freeze_value = _load_json(FREEZE_PATH, "demo accuracy freeze")
    _validate_self_hash(freeze_value, "freeze_sha256")
    freeze_raw = _read_regular(FREEZE_PATH, "demo accuracy freeze")
    freeze_record = _tracked_record(str(FREEZE_PATH.relative_to(PROJECT_ROOT)))
    if freeze_record["sha256"] != raw_hash(freeze_raw):
        raise DemoAccuracyError("freeze is not the committed HEAD blob")
    head, tree = _require_published(str(freeze_value["remote"]), str(freeze_value["remote_ref"]))
    _verify_freeze_lineage(freeze_value, head)
    _verify_bound_inputs(list(freeze_value["bound_inputs"]))
    manifest, tasks, tasks_raw = load_tasks()
    truth_value = _load_json(TRUTH_PATH, "demo accuracy truth")
    _verify_truth_against_pinned_inputs(truth_value, Path(args.metis_root), Path(args.node_path))
    if (
        freeze_value["truth_sha256"] != truth_value["truth_sha256"]
        or freeze_value["tasks_file_sha256"] != raw_hash(tasks_raw)
        or manifest["generation"] != freeze_value["generation"]
        or manifest["thresholds"] != freeze_value["thresholds"]
    ):
        raise DemoAccuracyError("tasks/truth/generation changed after freeze")
    if qlora._check_runtime() != freeze_value["runtime"]:
        raise DemoAccuracyError("qualification runtime changed after freeze")
    identities = {
        "base": qlora.evaluation_identity(qlora.BASE_CHECKPOINT, None),
        "adapter": qlora.evaluation_identity(qlora.BASE_CHECKPOINT, ADAPTER_PATH),
        "selection": _selection_identity(),
    }
    if identities != freeze_value["identities"]:
        raise DemoAccuracyError("base or adapter identity changed after freeze")
    _assert_artifact_root()
    if RUN_DIR.exists() or RUN_DIR.is_symlink():
        raise DemoAccuracyError(f"fixed run directory already exists: {RUN_DIR}")
    ignored = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(PROJECT_ROOT),
            "check-ignore",
            "-q",
            str(RUN_DIR.relative_to(PROJECT_ROOT)),
        ],
        check=False,
    )
    if ignored.returncode != 0:
        raise DemoAccuracyError("fixed run directory is not ignored")
    porcelain_before = _git("status", "--porcelain", "--untracked-files=all")
    if porcelain_before:
        raise DemoAccuracyError("worktree must remain clean before model execution")
    qlora._metal_jit_sandbox_canary()
    requests = [
        {"request_id": task["task_id"], "messages": build_messages(task), "max_tokens": 512}
        for task in tasks
    ]
    truth_by_id = {item["task_id"]: item for item in truth_value["tasks"]}
    try:
        RUN_DIR.mkdir(mode=0o700, parents=False, exist_ok=False)
    except FileExistsError as error:
        raise DemoAccuracyError("fixed run directory appeared during creation") from error
    _assert_run_root()
    _create_run_children()
    observations: dict[str, list[dict[str, Any]]] = {}
    output_records: dict[str, dict[str, Any]] = {}
    with _pinned_snapshot(Path(args.metis_root), Path(args.node_path)) as snapshot:
        normalizer = lambda source: _describe_source_in_snapshot(snapshot, source)  # noqa: E731
        for label, adapter_enabled in (("base", False), ("adapter", True)):
            responses = qlora._bounded_worker(
                _worker_command(adapter_enabled), requests, qlora.LIMITS["hours"] * 3600
            )
            raw_candidates = _candidate_lines(tasks, responses)
            candidate_path = _write_run_file(RUN_DIR / label, "candidates.jsonl", raw_candidates)
            output_records[label] = {
                "path": str(candidate_path.relative_to(PROJECT_ROOT)),
                "bytes": len(raw_candidates),
                "sha256": raw_hash(raw_candidates),
            }
            observations[label] = [
                score_candidate(task, response, truth_by_id[task["task_id"]], normalizer)
                for task, response in zip(tasks, responses, strict=True)
            ]
    _verify_bound_inputs(list(freeze_value["bound_inputs"]))
    if _git("status", "--porcelain", "--untracked-files=all") != porcelain_before:
        raise DemoAccuracyError("tracked worktree changed during model execution")
    decision = gate_arithmetic(observations["base"], observations["adapter"])
    report_body: dict[str, Any] = {
        "schema_version": 1,
        "status": "complete",
        "authority_scope": EXECUTION_AUTHORITY_SCOPE,
        "head": head,
        "tree": tree,
        "freeze_sha256": freeze_value["freeze_sha256"],
        "freeze_file_sha256": raw_hash(freeze_raw),
        "outputs": output_records,
        "observations": observations,
        "decision": decision,
        "model_outputs_observed": True,
        "training_input_allowed": False,
        "nonclaims": NONCLAIMS,
    }
    report_body["report_sha256"] = canonical_hash(report_body)
    _write_run_file(RUN_DIR, "report.json", canonical_bytes(report_body) + b"\n")
    print(
        json.dumps(
            {
                "event": "demo_accuracy_run",
                "verdict": decision["verdict"],
                "base": decision["base"]["semantic_correct"],
                "adapter": decision["adapter"]["semantic_correct"],
                "delta_qlora": decision["delta_qlora"],
            },
            sort_keys=True,
        )
    )
    return 0 if decision["verdict"] == PASS_VERDICT else 1


def _verified_run_file_roster() -> set[Path]:
    _assert_run_root()
    expected_files = {
        RUN_DIR / "base/candidates.jsonl",
        RUN_DIR / "adapter/candidates.jsonl",
        RUN_DIR / "report.json",
    }
    expected_directories = {RUN_DIR / "base", RUN_DIR / "adapter"}
    actual_files: set[Path] = set()
    actual_directories: set[Path] = set()
    for path in RUN_DIR.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise DemoAccuracyError("ignored run tree contains a symlink")
        if stat.S_ISDIR(metadata.st_mode):
            actual_directories.add(path)
        elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
            actual_files.add(path)
        else:
            raise DemoAccuracyError("ignored run tree contains a special or linked file")
    if actual_files != expected_files or actual_directories != expected_directories:
        raise DemoAccuracyError("ignored run artifact roster differs from the fixed contract")
    return expected_files


def evidence(args: argparse.Namespace) -> int:
    if EVIDENCE_PATH.exists() or EVIDENCE_PATH.is_symlink():
        raise DemoAccuracyError(f"evidence output already exists: {EVIDENCE_PATH}")
    freeze_value = _load_json(FREEZE_PATH, "demo accuracy freeze")
    _validate_self_hash(freeze_value, "freeze_sha256")
    freeze_raw = _read_regular(FREEZE_PATH, "demo accuracy freeze")
    freeze_record = _tracked_record(str(FREEZE_PATH.relative_to(PROJECT_ROOT)))
    if freeze_record["sha256"] != raw_hash(freeze_raw):
        raise DemoAccuracyError("evidence freeze is not the committed HEAD blob")
    head, tree = _require_published(str(freeze_value["remote"]), str(freeze_value["remote_ref"]))
    _verify_freeze_lineage(freeze_value, head)
    _verify_bound_inputs(list(freeze_value["bound_inputs"]))
    manifest, tasks, tasks_raw = load_tasks()
    truth_value = _load_json(TRUTH_PATH, "demo accuracy truth")
    _verify_truth_against_pinned_inputs(truth_value, Path(args.metis_root), Path(args.node_path))
    if (
        freeze_value["truth_sha256"] != truth_value["truth_sha256"]
        or freeze_value["tasks_file_sha256"] != raw_hash(tasks_raw)
        or manifest["generation"] != freeze_value["generation"]
        or manifest["thresholds"] != freeze_value["thresholds"]
    ):
        raise DemoAccuracyError("evidence tasks or truth differ from the freeze")
    identities = {
        "base": qlora.evaluation_identity(qlora.BASE_CHECKPOINT, None),
        "adapter": qlora.evaluation_identity(qlora.BASE_CHECKPOINT, ADAPTER_PATH),
        "selection": _selection_identity(),
    }
    if (
        qlora._check_runtime() != freeze_value["runtime"]
        or identities != freeze_value["identities"]
    ):
        raise DemoAccuracyError("evidence runtime or model identity differs from the freeze")
    report_path = RUN_DIR / "report.json"
    report = _load_json(report_path, "demo accuracy report")
    _validate_self_hash(report, "report_sha256")
    expected_paths = _verified_run_file_roster()
    records = [
        _source_record(path, f"run artifact {path.name}")
        for path in sorted(expected_paths, key=lambda item: item.as_posix())
    ]
    candidate_records = {
        label: _source_record(RUN_DIR / label / "candidates.jsonl", f"{label} candidates")
        for label in ("base", "adapter")
    }
    truth_by_id = {item["task_id"]: item for item in truth_value["tasks"]}
    observations: dict[str, list[dict[str, Any]]] = {}
    with _pinned_snapshot(Path(args.metis_root), Path(args.node_path)) as snapshot:
        normalizer = lambda source: _describe_source_in_snapshot(snapshot, source)  # noqa: E731
        for label in ("base", "adapter"):
            responses = _candidate_responses(RUN_DIR / label / "candidates.jsonl", tasks)
            observations[label] = [
                score_candidate(task, response, truth_by_id[task["task_id"]], normalizer)
                for task, response in zip(tasks, responses, strict=True)
            ]
    decision = gate_arithmetic(observations["base"], observations["adapter"])
    required_report_keys = {
        "schema_version",
        "status",
        "authority_scope",
        "head",
        "tree",
        "freeze_sha256",
        "freeze_file_sha256",
        "outputs",
        "observations",
        "decision",
        "model_outputs_observed",
        "training_input_allowed",
        "nonclaims",
        "report_sha256",
    }
    if (
        set(report) != required_report_keys
        or report.get("schema_version") != 1
        or report.get("status") != "complete"
        or report.get("authority_scope") != EXECUTION_AUTHORITY_SCOPE
        or report.get("head") != head
        or report.get("tree") != tree
        or report.get("freeze_sha256") != freeze_value["freeze_sha256"]
        or report.get("freeze_file_sha256") != raw_hash(freeze_raw)
        or report.get("outputs") != candidate_records
        or report.get("observations") != observations
        or report.get("decision") != decision
        or report.get("model_outputs_observed") is not True
        or report.get("training_input_allowed") is not False
        or report.get("nonclaims") != NONCLAIMS
    ):
        raise DemoAccuracyError("ignored report differs from the reconstructed paired gate")
    _verify_bound_inputs(list(freeze_value["bound_inputs"]))
    _verified_run_file_roster()
    redacted_observations = {
        label: [
            {
                key: item[key]
                for key in (
                    "task_id",
                    "family",
                    "output_kind",
                    "semantic_correct",
                    "critical_failure",
                    "failure_code",
                    "invented_identifiers",
                    "candidate_sha256",
                    "normalized_sha256",
                    "expected_normalized_sha256",
                )
            }
            for item in observations[label]
        ]
        for label in ("base", "adapter")
    }
    body: dict[str, Any] = {
        "schema_version": 1,
        "evidence_id": EVIDENCE_ID,
        "status": "verified_local_cooperative",
        "authority_scope": report["authority_scope"],
        "execution": {
            "head": report["head"],
            "tree": report["tree"],
            "freeze_sha256": report["freeze_sha256"],
            "freeze_file_sha256": report["freeze_file_sha256"],
            "report_sha256": report["report_sha256"],
            "run_dir": str(RUN_DIR.relative_to(PROJECT_ROOT)),
            "files": records,
        },
        "observations": redacted_observations,
        "decision": decision,
        "model_outputs_observed": True,
        "training_input_allowed": False,
        "nonclaims": NONCLAIMS,
    }
    body["evaluation_sha256"] = canonical_hash(body)
    _atomic_json(EVIDENCE_PATH, body)
    print(
        json.dumps(
            {
                "event": "demo_accuracy_evidence",
                "verdict": body["decision"]["verdict"],
                "evaluation_sha256": body["evaluation_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0 if body["decision"]["verdict"] == PASS_VERDICT else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("mode", choices=("truth", "freeze", "run", "evidence"))
    result.add_argument("--metis-root", type=Path, default=DEFAULT_METIS_ROOT)
    result.add_argument("--node-path", type=Path, default=DEFAULT_NODE)
    result.add_argument("--remote", default="origin")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        operation = {"truth": truth, "freeze": freeze, "run": run, "evidence": evidence}[args.mode]
        return operation(args)
    except (DemoAccuracyError, qlora.RuntimeContractError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
