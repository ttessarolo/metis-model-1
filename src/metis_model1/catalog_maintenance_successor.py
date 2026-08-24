"""Single-use prompt-cure successor for the catalog maintenance probe.

The completed v1 probe is immutable.  This module owns a fresh public-synthetic
roster, freeze, output directory, and decision.  It reuses only the already
verified technical primitives (checkpoint, pinned Metis snapshot and retrieval
receipt); no v1 model output, score, expected skeleton, or run artifact enters
this contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import select
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metis_model1 import catalog_maintenance_probe as common
from metis_model1.catalog_retrieval_refresh import _pinned_snapshot

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROBE_MANIFEST = PROJECT_ROOT / "manifests/catalog-maintenance-successor-probe-v1.json"
PROBE_SCHEMA = PROJECT_ROOT / "schemas/catalog-maintenance-successor-probe.schema.json"
FREEZE_SCHEMA = PROJECT_ROOT / "schemas/catalog-maintenance-successor-freeze.schema.json"
FREEZE_OUTPUT = PROJECT_ROOT / "manifests/catalog-maintenance-successor-freeze-v1.json"
RUN_OUTPUT_RELATIVE = "artifacts/catalog-maintenance-successor-v1"
DEFAULT_RUN_DIR = PROJECT_ROOT / RUN_OUTPUT_RELATIVE

PROBE_MANIFEST_SHA256 = "sha256:7452f06d84c3e4820d75d784e94e4aa28d7b2641e1ec5e9850949470b3a836c5"
PROBE_MANIFEST_FILE_SHA256 = (
    "sha256:92c7f5bc85a3c8bb6d2a202c47c4027a25c7ce070599986d300148e2fbb28a7f"
)
PROBE_SCHEMA_SHA256 = "sha256:aabffb0cf60a6308e2494b01abd6663cc0fde775b853827cd3f935feba3c0e50"
FREEZE_SCHEMA_SHA256 = "sha256:ac5517fb3930faf4062b3c3316aa2a02d40d44ee994eb41d1602c1a464a24459"

SYSTEM_PROMPT = "\n".join(
    (
        "You are Metis Model 1. Produce exactly one complete canonical Metis 0.43 ",
        "catalog source and no explanation.",
        "",
        "Mandatory syntax contract:",
        "- Return plain source only. The first line must be exactly: metis 0.43",
        "- A complete catalog contains catalog, driver, index, id, and fields blocks.",
        "- Scalar domains follow their type: name keyword enum(N), name keyword open, or",
        '  name keyword values ["A", "B"].',
        "- Never emit name enum(N), domain/name/type blocks, or colon-style field syntax.",
        "- A nested field uses object braces, for example: metadata object { code ",
        "  keyword enum(9) }.",
        "- Bounded external domains use keyword enum(N). Open live-index domains use ",
        "  keyword open. Only a tiny stable domain explicitly supplied by the request ",
        "  may use keyword values [...].",
        "- Retrieved values are data, not catalog syntax. Never materialize them unless ",
        "  the request explicitly declares a tiny stable inline domain.",
        "",
        "Canonical syntax example only; never copy its identifiers or cardinality:",
        "metis 0.43",
        "catalog example.items {",
        "  driver opensearch",
        '  index "example_items"',
        "  id item_id",
        "  fields {",
        "    item_id keyword",
        "    status keyword enum(7)",
        "  }",
        "}",
    )
)

NONCLAIMS = [
    "no_accuracy_claim",
    "no_promotion_claim",
    "no_training_authority",
    "no_tenant_dataset_authority",
    "no_independent_accuracy_denominator",
    "no_live_execution_attestation",
    "nonpromotable",
]


class CatalogMaintenanceSuccessorError(RuntimeError):
    """Raised when the successor cannot satisfy its fixed contract."""


def _raise_common(error: Exception) -> CatalogMaintenanceSuccessorError:
    return CatalogMaintenanceSuccessorError(str(error))


def load_probe_contract(
    root: Path = PROJECT_ROOT,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    try:
        manifest, manifest_raw = common._load_json(
            root / PROBE_MANIFEST.relative_to(PROJECT_ROOT), "successor probe manifest"
        )
        if (
            not isinstance(manifest, dict)
            or common.raw_hash(manifest_raw) != PROBE_MANIFEST_FILE_SHA256
            or manifest.get("manifest_sha256")
            != common.canonical_hash(
                {key: value for key, value in manifest.items() if key != "manifest_sha256"}
            )
            or manifest.get("manifest_sha256") != PROBE_MANIFEST_SHA256
        ):
            raise CatalogMaintenanceSuccessorError(
                "successor probe manifest differs from its fixed digest"
            )
        schema = common._schema(
            root / PROBE_SCHEMA.relative_to(PROJECT_ROOT),
            PROBE_SCHEMA_SHA256,
            "successor probe schema",
        )
        common._validate(manifest, schema, "successor probe manifest")
        case_schema = schema.get("$defs", {}).get("case")
        if not isinstance(case_schema, dict):
            raise CatalogMaintenanceSuccessorError("successor probe schema has no case definition")
        case_contract = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": schema["$defs"],
            "$ref": "#/$defs/case",
        }
        cases: list[dict[str, Any]] = []
        for descriptor in manifest["cases"]:
            case_path = root / descriptor["fixture_path"]
            case, case_raw = common._load_json(case_path, f"successor case {descriptor['case_id']}")
            expected = next(
                item for item in manifest["files"] if item["path"] == descriptor["fixture_path"]
            )
            if (
                len(case_raw) != expected["bytes"]
                or common.raw_hash(case_raw) != expected["sha256"]
            ):
                raise CatalogMaintenanceSuccessorError(
                    f"successor case hash drift: {descriptor['case_id']}"
                )
            common._validate(case, case_contract, f"successor case {descriptor['case_id']}")
            if not isinstance(case, dict) or case.get("case_id") != descriptor["case_id"]:
                raise CatalogMaintenanceSuccessorError(
                    f"successor case identity drift: {descriptor['case_id']}"
                )
            cases.append(case)
        if len(cases) != 8 or len({case["case_id"] for case in cases}) != 8:
            raise CatalogMaintenanceSuccessorError("successor must contain 8 distinct cases")
        return manifest, schema, cases
    except CatalogMaintenanceSuccessorError:
        raise
    except Exception as error:  # noqa: BLE001 - contract boundary
        raise _raise_common(error) from error


def build_messages(
    case: Mapping[str, Any], retrieval: Mapping[str, Any] | None = None
) -> list[dict[str, str]]:
    user = [f"Task family: {case['family']}.", "User request:\n" + case["prompt"]["request"]]
    if "before_source" in case["prompt"]:
        user.append("Current source:\n" + case["prompt"]["before_source"].rstrip())
    if retrieval is not None:
        user.append(
            "Verified public-synthetic per-field retrieval: video.genre returned "
            f"{retrieval['value']} as editorial data; retrieved count is {retrieval['size']}. "
            "Use it only to respect the request's retrieval boundary."
        )
    user.append("Return the complete corrected source now.")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.rstrip()},
        {"role": "user", "content": "\n\n".join(user)},
    ]
    expected = case["target"]["expected_source"].strip()
    if any(expected in message["content"] for message in messages):
        raise CatalogMaintenanceSuccessorError(f"target leakage in messages: {case['case_id']}")
    return messages


def build_repair_message(failure_code: str | None) -> str:
    if failure_code == "missing_metis_0_43_prefix":
        diagnostic = "The output did not begin with the exact required first line `metis 0.43`."
    elif failure_code in {
        "multiple_code_fences",
        "text_outside_code_fence",
        "unbalanced_code_fence",
    }:
        diagnostic = "The output contained wrapper text or an invalid code fence."
    elif failure_code == "catalog describe rejected candidate":
        diagnostic = (
            "The catalog parser/validator rejected the source. Check the complete catalog wrapper "
            "and remember that a domain marker follows the scalar type `keyword`."
        )
    else:
        diagnostic = (
            "The source compiled but its catalog skeleton did not satisfy the request. Preserve "
            "unrelated structure and apply only the requested domain representation."
        )
    return (
        f"{diagnostic} Repair without inventing values or identifiers. Return plain complete Metis "
        "source only; the first line must be exactly `metis 0.43`."
    )


def score_candidate(
    case: Mapping[str, Any],
    source: str | None,
    normalized: Mapping[str, Any] | None,
    retrieval_error: str | None = None,
    expected_skeleton: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    forbidden_hits = [
        fragment
        for fragment in case["target"]["forbidden_fragments"]
        if source is not None and fragment in source
    ]
    required_missing = [
        fragment
        for fragment in case["target"]["required_fragments"]
        if source is None or fragment not in source
    ]
    tiny_inline = str(case.get("construct", "")).startswith("tiny_stable_inline")
    legacy_inline = int(
        any("values" in item for item in forbidden_hits)
        and any("enum(" in item or " open" in item for item in case["target"]["required_fragments"])
    )
    invented_values = int(
        source is not None and not tiny_inline and bool(common.INLINE_VALUES_RE.search(source))
    )
    skeleton_match = expected_skeleton is not None and normalized == expected_skeleton
    critical = int(retrieval_error is not None or source is None or normalized is None)
    return {
        "semantic_correct": int(
            not required_missing
            and not forbidden_hits
            and retrieval_error is None
            and normalized is not None
            and skeleton_match
        ),
        "skeleton_match": skeleton_match,
        "critical_failure": critical,
        "invented_values": invented_values,
        "legacy_inline": legacy_inline,
        "retrieval_error": int(retrieval_error is not None),
        "required_missing": required_missing,
        "forbidden_hits": forbidden_hits,
        "retrieval_error_text": retrieval_error,
    }


def gate_arithmetic(observations: list[Mapping[str, Any]]) -> dict[str, Any]:
    _manifest, _schema, cases = load_probe_contract()
    expected_roots = {case["case_id"]: case["provenance"]["semantic_root"] for case in cases}
    required_keys = {
        "case_id",
        "root_id",
        "semantic_correct",
        "skeleton_match",
        "critical_failure",
        "invented_values",
        "legacy_inline",
        "retrieval_error",
        "required_missing",
        "forbidden_hits",
        "retrieval_error_text",
    }
    for item in observations:
        if set(item) != required_keys:
            raise CatalogMaintenanceSuccessorError(
                "successor observation has missing or unexpected fields"
            )
        if not isinstance(item["case_id"], str) or not item["case_id"]:
            raise CatalogMaintenanceSuccessorError("successor observation case_id is invalid")
        if not isinstance(item["root_id"], str) or not item["root_id"]:
            raise CatalogMaintenanceSuccessorError("successor observation root_id is invalid")
        binary_keys = {
            "semantic_correct",
            "critical_failure",
            "invented_values",
            "legacy_inline",
            "retrieval_error",
        }
        if any(type(item[key]) is not int or item[key] not in (0, 1) for key in binary_keys):
            raise CatalogMaintenanceSuccessorError("successor observation score is not binary")
        if type(item["skeleton_match"]) is not bool:
            raise CatalogMaintenanceSuccessorError(
                "successor observation skeleton_match is not boolean"
            )
        if any(
            not isinstance(item[key], list)
            or any(not isinstance(value, str) for value in item[key])
            for key in ("required_missing", "forbidden_hits")
        ):
            raise CatalogMaintenanceSuccessorError("successor observation fragments are invalid")
        if item["retrieval_error_text"] is not None and not isinstance(
            item["retrieval_error_text"], str
        ):
            raise CatalogMaintenanceSuccessorError(
                "successor observation retrieval error text is invalid"
            )
        if item["semantic_correct"] == 1 and (
            item["skeleton_match"] is not True
            or item["critical_failure"] != 0
            or item["required_missing"]
            or item["forbidden_hits"]
            or item["retrieval_error_text"] is not None
        ):
            raise CatalogMaintenanceSuccessorError(
                "successor observation semantic score is inconsistent"
            )
    case_ids = [item["case_id"] for item in observations]
    if len(case_ids) != len(set(case_ids)):
        raise CatalogMaintenanceSuccessorError("successor observations contain duplicate IDs")
    counts = {
        key: sum(int(item.get(key, 0)) for item in observations)
        for key in (
            "critical_failure",
            "invented_values",
            "legacy_inline",
            "retrieval_error",
            "semantic_correct",
        )
    }
    counts.update(
        {
            "cases_in": len(observations),
            "cases_out": len(observations),
            "cases_distinct": len(set(case_ids)),
            "gaps": max(0, 8 - len(set(case_ids))),
        }
    )
    canonical_roster = set(case_ids) == set(expected_roots) and all(
        item.get("root_id") == expected_roots.get(item.get("case_id")) for item in observations
    )
    green = (
        canonical_roster
        and counts["cases_in"] == 8
        and counts["cases_out"] == 8
        and counts["cases_distinct"] == 8
        and counts["gaps"] == 0
        and counts["semantic_correct"] == 8
        and all(
            counts[key] == 0
            for key in ("critical_failure", "invented_values", "legacy_inline", "retrieval_error")
        )
    )
    return {
        "verdict": "NO_RETRAIN_PROMPT_CURE" if green else "DIAGNOSE",
        "counts": counts,
        "training_authorized": False,
        "promotion_claim": False,
        "accuracy_claim": False,
    }


def _bound_paths(manifest: Mapping[str, Any]) -> list[str]:
    return [
        PROBE_MANIFEST.relative_to(PROJECT_ROOT).as_posix(),
        PROBE_SCHEMA.relative_to(PROJECT_ROOT).as_posix(),
        FREEZE_SCHEMA.relative_to(PROJECT_ROOT).as_posix(),
        "schemas/catalog-maintenance-successor-evaluation.schema.json",
        "schemas/catalog-maintenance-successor-decision.schema.json",
        "docs/17-catalog-prompt-cure-successor.md",
        Path(__file__).relative_to(PROJECT_ROOT).as_posix(),
        "src/metis_model1/catalog_maintenance_successor_evidence.py",
        "src/metis_model1/contracts.py",
        "tests/test_catalog_maintenance_successor_manifest.py",
        "tests/test_catalog_maintenance_successor.py",
        "tests/test_catalog_maintenance_successor_evidence.py",
        "tests/test_contracts.py",
        "src/metis_model1/catalog_maintenance_probe.py",
        "src/metis_model1/catalog_maintenance_pin.py",
        "src/metis_model1/catalog_retrieval.py",
        "src/metis_model1/catalog_retrieval_refresh.py",
        "src/metis_model1/oracles.py",
        "manifests/catalog-retrieval-public-synthetic-v1.json",
        "manifests/catalog-retrieval-execution-v1.json",
        "schemas/catalog-retrieval-execution-receipt.schema.json",
        "manifests/catalog-maintenance-pin-v1.json",
        "schemas/catalog-maintenance-pin.schema.json",
        *common.PUBLIC_FIXTURE_PATHS,
        *[item["path"] for item in manifest["files"]],
    ]


def _bound_input_records(project: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in _bound_paths(manifest):
        raw = subprocess.check_output(
            ["/usr/bin/git", "-C", str(project), "show", f"HEAD:{path}"], timeout=60
        )
        tree_row = common._git(project, "ls-tree", "HEAD", "--", path).split()
        if len(tree_row) != 4 or tree_row[1] != "blob" or tree_row[3] != path:
            raise CatalogMaintenanceSuccessorError(
                f"successor bound input is not one committed blob: {path}"
            )
        records.append(
            {
                "path": path,
                "bytes": len(raw),
                "sha256": common.raw_hash(raw),
                "git_blob_oid": tree_row[2],
            }
        )
    return records


def _runtime_identity(args: argparse.Namespace) -> dict[str, Any]:
    sandbox_policy = _successor_worker_sandbox_policy(Path(args.model_path))
    return {
        "successor_runner": common._runtime_identity(Path(__file__), "successor runner"),
        "common_runner": common._runtime_identity(Path(common.__file__), "common probe runner"),
        "worker_script": common._runtime_identity(Path(args.worker_script), "worker script"),
        "worker_python": common._python_runtime_identity(Path(args.worker_python)),
        "checkpoint_report": common._runtime_identity(
            Path(args.checkpoint_report), "checkpoint report"
        ),
        "sandbox_policy_sha256": common.raw_hash(sandbox_policy.encode("utf-8")),
    }


def _successor_worker_sandbox_policy(checkpoint_path: Path) -> str:
    """Prevent the worker from writing project state during generation."""

    policy = common._worker_sandbox_policy(checkpoint_path)
    return policy + f" (deny file-write* (subpath {json.dumps(str(PROJECT_ROOT))}))"


def _project_porcelain_sha256() -> str:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(PROJECT_ROOT), "status", "--porcelain=v1", "-z"],
        check=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    return "sha256:" + hashlib.sha256(result.stdout).hexdigest()


def _require_safe_output_dir(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise CatalogMaintenanceSuccessorError("successor output path is not a regular directory")
    current = path
    while current != PROJECT_ROOT:
        if current.is_symlink():
            raise CatalogMaintenanceSuccessorError("successor output path crosses a symlink")
        current = current.parent
        if not current.exists():
            raise CatalogMaintenanceSuccessorError("successor output parent does not exist")


def _freeze_body(args: argparse.Namespace) -> dict[str, Any]:
    manifest, _schema, cases = load_probe_contract()
    remote_ref = common.current_remote_ref(PROJECT_ROOT, args.remote, args.remote_ref)
    head, tree = common.require_head_published(PROJECT_ROOT, args.remote, remote_ref)
    bound = _bound_input_records(PROJECT_ROOT, manifest)
    common._require_bound_worktree_matches_head(PROJECT_ROOT, bound)
    node_path = common._node_argument(args.node_path)
    pin_report = common.pin.verify_catalog_maintenance_pin(Path(args.metis_root), node_path)
    if pin_report["status"] != "verified_local_cooperative":
        raise CatalogMaintenanceSuccessorError("catalog pin is not verified")
    _retrieval_manifest, retrieval_receipt, pin_manifest = common._retrieval_contract()
    curated = common._retrieval_curated(Path(args.metis_root), node_path)
    checkpoint = common._checkpoint_identity(Path(args.model_path), Path(args.checkpoint_report))
    runtime = _runtime_identity(args)
    tasks: list[dict[str, Any]] = []
    with _pinned_snapshot(Path(args.metis_root), node_path) as snapshot:
        for case in cases:
            retrieval = curated if case["retrieval"]["kind"] == "public_synthetic_value" else None
            messages = build_messages(case, retrieval)
            normalized, receipt = common._describe_source_in_snapshot(
                snapshot, case["target"]["expected_source"]
            )
            tasks.append(
                {
                    "case_id": case["case_id"],
                    "family": case["family"],
                    "mode": case["mode"],
                    "root_id": case["provenance"]["semantic_root"],
                    "messages": messages,
                    "messages_sha256": common.canonical_hash(messages),
                    "expected_skeleton": normalized,
                    "expected_skeleton_sha256": common.canonical_hash(normalized),
                    "expected_describe_receipt_sha256": receipt["receipt_sha256"],
                    "retrieval": retrieval,
                    "model_output_observed": False,
                }
            )
    body = {
        "schema_version": 1,
        "freeze_id": "catalog-maintenance-successor-freeze/v1",
        "status": "frozen_before_model_output",
        "preimage_commit": head,
        "preimage_tree": tree,
        "remote": args.remote,
        "remote_ref": remote_ref,
        "probe_manifest_sha256": PROBE_MANIFEST_SHA256,
        "probe_manifest_file_sha256": PROBE_MANIFEST_FILE_SHA256,
        "probe_schema_sha256": PROBE_SCHEMA_SHA256,
        "bound_inputs": bound,
        "catalog_pin": {
            "revision": pin_manifest["revision"],
            "tree": pin_manifest["tree"],
            "manifest_sha256": common.pin.manifest_sha256(pin_manifest),
            "verification": pin_report["status"],
        },
        "retrieval": {
            "manifest_sha256": common.RETRIEVAL_MANIFEST_SHA256,
            "receipt_file_sha256": common.RETRIEVAL_RECEIPT_SHA256,
            "receipt_self_sha256": retrieval_receipt["receipt_sha256"],
            "curated": curated,
        },
        "checkpoint": checkpoint,
        "runtime": runtime,
        "run_dir": RUN_OUTPUT_RELATIVE,
        "model": manifest["model"],
        "counts": {"cases_in": 8, "cases_out": 8, "cases_distinct": 8, "gaps": 0},
        "tasks": tasks,
        "model_outputs_observed": False,
        "training_authorized": False,
        "nonclaims": NONCLAIMS,
    }
    body["freeze_sha256"] = common.canonical_hash(body)
    return body


def freeze(args: argparse.Namespace) -> int:
    output = Path(args.freeze_output).resolve()
    if output != FREEZE_OUTPUT.resolve():
        raise CatalogMaintenanceSuccessorError("successor freeze output path is fixed")
    if output.exists():
        raise CatalogMaintenanceSuccessorError(f"successor freeze already exists: {output}")
    run_dir = Path(args.run_dir).resolve()
    if run_dir != DEFAULT_RUN_DIR.resolve():
        raise CatalogMaintenanceSuccessorError("successor run path is fixed")
    if run_dir.exists():
        raise CatalogMaintenanceSuccessorError(f"successor run already exists: {run_dir}")
    body = _freeze_body(args)
    schema = common._schema(FREEZE_SCHEMA, FREEZE_SCHEMA_SHA256, "successor freeze schema")
    common._validate(body, schema, "successor freeze")
    common._atomic_write(output, common.canonical_bytes(body) + b"\n")
    print(json.dumps({"event": "successor_freeze_complete", "cases": 8}, sort_keys=True))
    return 0


def _frozen_run_dir(freeze_manifest: Mapping[str, Any], requested: Path) -> Path:
    lexical = requested.absolute()
    cursor = lexical
    while cursor != PROJECT_ROOT:
        if cursor.is_symlink():
            raise CatalogMaintenanceSuccessorError("successor run path crosses a symlink")
        cursor = cursor.parent
    output = requested.resolve()
    try:
        relative = output.relative_to(PROJECT_ROOT).as_posix()
    except ValueError as error:
        raise CatalogMaintenanceSuccessorError(
            "successor run path is outside the project"
        ) from error
    if freeze_manifest.get("run_dir") != RUN_OUTPUT_RELATIVE or relative != RUN_OUTPUT_RELATIVE:
        raise CatalogMaintenanceSuccessorError("successor run path differs from its freeze")
    return output


def _read_worker_json(
    worker: subprocess.Popen[bytes], buffer: bytearray, *, deadline: float, label: str
) -> dict[str, Any]:
    if worker.stdout is None:
        raise CatalogMaintenanceSuccessorError("worker stdout is unavailable")
    descriptor = worker.stdout.fileno()
    while True:
        newline = buffer.find(b"\n")
        if newline >= 0:
            raw = bytes(buffer[:newline])
            del buffer[: newline + 1]
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise CatalogMaintenanceSuccessorError(f"{label} is not JSON") from error
            if not isinstance(value, dict):
                raise CatalogMaintenanceSuccessorError(f"{label} is not an object")
            return value
        if len(buffer) > common.MAX_OUTPUT_BYTES:
            raise CatalogMaintenanceSuccessorError(f"{label} exceeds its byte cap")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CatalogMaintenanceSuccessorError(f"{label} timed out")
        readable, _, _ = select.select([descriptor], [], [], remaining)
        if not readable:
            raise CatalogMaintenanceSuccessorError(f"{label} timed out")
        chunk = os.read(descriptor, min(64 * 1024, common.MAX_OUTPUT_BYTES + 1 - len(buffer)))
        if not chunk:
            raise CatalogMaintenanceSuccessorError(f"worker exited before {label}")
        buffer.extend(chunk)


def _worker_request(
    worker: subprocess.Popen[bytes],
    buffer: bytearray,
    request_id: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    global_deadline: float,
) -> dict[str, Any]:
    if worker.stdin is None:
        raise CatalogMaintenanceSuccessorError("worker stdin is unavailable")
    payload = (
        json.dumps(
            {
                "event": "generate",
                "request_id": request_id,
                "messages": messages,
                "max_tokens": max_tokens,
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    worker.stdin.write(payload)
    worker.stdin.flush()
    response = _read_worker_json(
        worker,
        buffer,
        deadline=min(global_deadline, time.monotonic() + common.MAX_WORKER_RESPONSE_SECONDS),
        label="successor worker generation",
    )
    if response.get("event") != "generation" or response.get("request_id") != request_id:
        raise CatalogMaintenanceSuccessorError("worker response identity mismatch")
    if float(response.get("peak_metal_gb", 0)) > common.MAX_MODEL_METAL_GB:
        raise CatalogMaintenanceSuccessorError("Metal memory limit exceeded")
    return response


def run(args: argparse.Namespace) -> int:
    global_deadline = time.monotonic() + common.MAX_WALL_SECONDS
    freeze_path = Path(args.freeze_output).resolve(strict=True)
    if freeze_path != FREEZE_OUTPUT.resolve():
        raise CatalogMaintenanceSuccessorError("successor freeze input path is fixed")
    freeze_manifest, freeze_raw = common._load_json(
        freeze_path, "successor freeze", maximum=16 * 1024 * 1024
    )
    if not isinstance(freeze_manifest, dict) or freeze_manifest.get(
        "freeze_sha256"
    ) != common.canonical_hash(
        {key: value for key, value in freeze_manifest.items() if key != "freeze_sha256"}
    ):
        raise CatalogMaintenanceSuccessorError("successor freeze seal mismatch")
    if (
        freeze_manifest.get("status") != "frozen_before_model_output"
        or freeze_manifest.get("model_outputs_observed") is not False
    ):
        raise CatalogMaintenanceSuccessorError("successor freeze is not executable")
    schema = common._schema(FREEZE_SCHEMA, FREEZE_SCHEMA_SHA256, "successor freeze schema")
    common._validate(freeze_manifest, schema, "successor freeze")
    output_dir = _frozen_run_dir(freeze_manifest, Path(args.run_dir))
    if common._git_blob(
        PROJECT_ROOT, FREEZE_OUTPUT.relative_to(PROJECT_ROOT).as_posix()
    ) != common.raw_hash(freeze_raw):
        raise CatalogMaintenanceSuccessorError("successor freeze is not committed at HEAD")
    head, tree = common.require_head_published(
        PROJECT_ROOT, freeze_manifest["remote"], freeze_manifest["remote_ref"]
    )
    ancestor = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(PROJECT_ROOT),
            "merge-base",
            "--is-ancestor",
            freeze_manifest["preimage_commit"],
            head,
        ],
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    if ancestor.returncode != 0:
        raise CatalogMaintenanceSuccessorError("successor preimage is not an ancestor")
    manifest, _probe_schema, cases = load_probe_contract()
    bound = _bound_input_records(PROJECT_ROOT, manifest)
    common._require_bound_worktree_matches_head(PROJECT_ROOT, bound)
    if bound != freeze_manifest["bound_inputs"]:
        raise CatalogMaintenanceSuccessorError("successor bound inputs changed after freeze")
    porcelain_before = _project_porcelain_sha256()
    node_path = common._node_argument(args.node_path)
    pin_report = common.pin.verify_catalog_maintenance_pin(Path(args.metis_root), node_path)
    if pin_report["status"] != "verified_local_cooperative":
        raise CatalogMaintenanceSuccessorError("catalog pin is not verified")
    common._retrieval_contract()
    curated = common._retrieval_curated(Path(args.metis_root), node_path)
    if freeze_manifest["retrieval"]["curated"] != curated:
        raise CatalogMaintenanceSuccessorError("successor retrieval changed after freeze")
    checkpoint = common._checkpoint_identity(Path(args.model_path), Path(args.checkpoint_report))
    if checkpoint != freeze_manifest["checkpoint"]:
        raise CatalogMaintenanceSuccessorError("checkpoint changed after successor freeze")
    runtime = _runtime_identity(args)
    if runtime != freeze_manifest["runtime"]:
        raise CatalogMaintenanceSuccessorError("runtime changed after successor freeze")
    case_by_id = {case["case_id"]: case for case in cases}
    if [item["case_id"] for item in freeze_manifest["tasks"]] != [
        case["case_id"] for case in cases
    ]:
        raise CatalogMaintenanceSuccessorError("successor frozen roster/order drift")
    with _pinned_snapshot(Path(args.metis_root), node_path) as snapshot:
        for frozen_task in freeze_manifest["tasks"]:
            case = case_by_id[frozen_task["case_id"]]
            retrieval = curated if case["retrieval"]["kind"] == "public_synthetic_value" else None
            messages = build_messages(case, retrieval)
            if frozen_task["messages"] != messages or frozen_task[
                "messages_sha256"
            ] != common.canonical_hash(messages):
                raise CatalogMaintenanceSuccessorError(
                    f"successor frozen messages drift: {case['case_id']}"
                )
            normalized, receipt = common._describe_source_in_snapshot(
                snapshot, case["target"]["expected_source"]
            )
            if (
                frozen_task["expected_skeleton"] != normalized
                or frozen_task["expected_skeleton_sha256"] != common.canonical_hash(normalized)
                or frozen_task["expected_describe_receipt_sha256"] != receipt["receipt_sha256"]
            ):
                raise CatalogMaintenanceSuccessorError(
                    f"successor frozen oracle drift: {case['case_id']}"
                )
    if output_dir.exists():
        raise CatalogMaintenanceSuccessorError(f"successor run already exists: {output_dir}")
    _require_safe_output_dir(output_dir)
    ignored = (
        subprocess.run(
            [
                "/usr/bin/git",
                "-C",
                str(PROJECT_ROOT),
                "check-ignore",
                "-q",
                str(output_dir.relative_to(PROJECT_ROOT)),
            ],
            check=False,
        ).returncode
        == 0
    )
    if not ignored or not output_dir.is_relative_to(PROJECT_ROOT / "artifacts"):
        raise CatalogMaintenanceSuccessorError("successor output is not ignored artifacts")
    output_dir.mkdir(parents=True)
    sandbox_policy = _successor_worker_sandbox_policy(Path(checkpoint["path"]))
    command = [
        "/usr/bin/sandbox-exec",
        "-p",
        sandbox_policy,
        runtime["worker_python"]["invocation_path"],
        str(Path(args.worker_script).resolve(strict=True)),
        "--model-path",
        str(checkpoint["path"]),
        "--checkpoint-report",
        str(Path(args.checkpoint_report).resolve(strict=True)),
    ]
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "HF_HUB_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "PYTHONNOUSERSITE": "1",
    }
    observations: list[dict[str, Any]] = []
    with _pinned_snapshot(Path(args.metis_root), node_path) as describe_snapshot:  # noqa: SIM117
        with (output_dir / "worker.stderr.log").open("w", encoding="utf-8") as stderr:
            worker = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=False,
                bufsize=0,
                env=env,
            )
            buffer = bytearray()
            try:
                ready = _read_worker_json(
                    worker,
                    buffer,
                    deadline=min(
                        global_deadline, time.monotonic() + common.MAX_WORKER_READY_SECONDS
                    ),
                    label="successor worker readiness",
                )
                if (
                    ready.get("event") != "ready"
                    or ready.get("model_type") != "qwen3_5"
                    or ready.get("checkpoint_revision") != common.CHECKPOINT_REVISION
                ):
                    raise CatalogMaintenanceSuccessorError("worker readiness identity mismatch")
                common._require_checkpoint_metadata_unchanged(checkpoint)
                for case, frozen_task in zip(cases, freeze_manifest["tasks"], strict=True):
                    original = frozen_task["messages"]
                    current = original
                    attempts: list[dict[str, Any]] = []
                    final: dict[str, Any] | None = None
                    for index in range(manifest["model"]["max_repair_cycles"] + 1):
                        response = _worker_request(
                            worker,
                            buffer,
                            f"{case['case_id']}:{index}",
                            current,
                            manifest["model"]["max_tokens"],
                            global_deadline,
                        )
                        common._require_checkpoint_metadata_unchanged(checkpoint)
                        source, extraction_error = common._extract_source(
                            str(response.get("text", ""))
                        )
                        normalized = None
                        receipt_sha = None
                        failure_code = extraction_error
                        if source is not None:
                            try:
                                normalized, receipt = common._describe_source_in_snapshot(
                                    describe_snapshot, source
                                )
                                receipt_sha = receipt["receipt_sha256"]
                                failure_code = None
                            except Exception:  # noqa: BLE001 - intentionally redacted
                                failure_code = "catalog describe rejected candidate"
                        score = score_candidate(
                            case,
                            source,
                            normalized,
                            failure_code,
                            frozen_task["expected_skeleton"],
                        )
                        attempts.append(
                            {
                                "attempt": index,
                                "text": response.get("text", ""),
                                "text_sha256": common.raw_hash(
                                    str(response.get("text", "")).encode()
                                ),
                                "receipt_sha256": receipt_sha,
                                "score": score,
                            }
                        )
                        final = score
                        if score["semantic_correct"]:
                            break
                        current = [
                            *original,
                            {"role": "assistant", "content": str(response.get("text", ""))},
                            {
                                "role": "user",
                                "content": build_repair_message(failure_code),
                            },
                        ]
                    task_dir = output_dir / "tasks" / case["case_id"]
                    task_dir.mkdir(parents=True)
                    common._atomic_write(
                        task_dir / "attempts.json", common.canonical_bytes(attempts) + b"\n"
                    )
                    observations.append(
                        {
                            "case_id": case["case_id"],
                            "root_id": case["provenance"]["semantic_root"],
                            **(final or {}),
                        }
                    )
            finally:
                if worker.stdin:
                    try:
                        worker.stdin.write(b'{"event":"shutdown"}\n')
                        worker.stdin.flush()
                    except BrokenPipeError:
                        pass
                try:
                    worker.wait(timeout=30)
                except subprocess.TimeoutExpired as error:
                    worker.kill()
                    worker.wait(timeout=30)
                    raise CatalogMaintenanceSuccessorError("worker shutdown timed out") from error
                if worker.returncode != 0:
                    raise CatalogMaintenanceSuccessorError("worker exited non-zero")
    common._require_bound_worktree_matches_head(PROJECT_ROOT, bound)
    if _project_porcelain_sha256() != porcelain_before:
        raise CatalogMaintenanceSuccessorError("project worktree changed during successor run")
    decision = gate_arithmetic(observations)
    report = {
        "schema_version": 1,
        "status": "complete",
        "head": head,
        "tree": tree,
        "freeze_sha256": freeze_manifest["freeze_sha256"],
        "observations": observations,
        "decision": decision,
        "model_outputs_observed": True,
        "training_authorized": False,
    }
    common._atomic_write(output_dir / "report.json", common.canonical_bytes(report) + b"\n")
    print(
        json.dumps(
            {
                "event": "successor_complete",
                "verdict": decision["verdict"],
                "semantic_correct": decision["counts"]["semantic_correct"],
            },
            sort_keys=True,
        )
    )
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("mode", choices=("freeze", "run"))
    result.add_argument("--freeze-output", type=Path, default=FREEZE_OUTPUT)
    result.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    result.add_argument("--remote", default="origin")
    result.add_argument("--remote-ref", default=None)
    result.add_argument("--metis-root", type=Path, default=common.DEFAULT_METIS_ROOT)
    result.add_argument("--node-path", type=Path, default=common.DEFAULT_NODE)
    result.add_argument("--model-path", type=Path, default=common.DEFAULT_MODEL)
    result.add_argument("--checkpoint-report", type=Path, default=common.DEFAULT_CHECKPOINT_REPORT)
    result.add_argument("--worker-script", type=Path, default=common.DEFAULT_WORKER)
    result.add_argument("--worker-python", type=Path, default=common.DEFAULT_WORKER_PYTHON)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return freeze(args) if args.mode == "freeze" else run(args)
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
