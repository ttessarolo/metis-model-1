"""Fail-closed, offline command surface for the video semantic wave.

The commands in this module are deliberately file based.  They only consume
explicit caller-provided JSON/text files and pure contract functions; they do
not discover a tenant, contact a service, read a keychain, invoke a model, or
start training.  Sensitive projections and indexes are written only beneath
the explicit output directory.  Standard output contains a redacted write
receipt, never the input payload or generated semantic material.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metis_model1.video_brain_grounding import ground_request, validate_grounding_receipt
from metis_model1.video_catalog_projection import (
    build_catalog_semantic_projection,
    validate_catalog_projection_receipt,
)
from metis_model1.video_grounding_benchmark import benchmark_revision
from metis_model1.video_grounding_evaluation import evaluate_paired_observations
from metis_model1.video_local_census import (
    build_local_census,
    validate_local_census_receipt,
)
from metis_model1.video_private_io import (
    VideoPrivateIOError,
    prepare_private_store,
    write_private_bytes_atomic,
)
from metis_model1.video_semantic_index import (
    build_semantic_index,
    validate_semantic_index_receipt,
)
from metis_model1.video_weight_verdict import decide_weight_verdict

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OFFLINE_OPERATIONS = frozenset(
    {"normalize", "census", "index", "ground", "evaluate", "weight-verdict"}
)
_OUTPUT_ROOT_BY_OPERATION = {
    "normalize": "work-items",
    "census": "work-items",
    "index": "work-items",
    "ground": "work-items",
    "evaluate": "benchmark-runs",
    "weight-verdict": "receipts",
}


class VideoSemanticsCLIError(ValueError):
    """A caller/input/output error that is safe to report only as a code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VideoSemanticsCLIError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise VideoSemanticsCLIError("JSON_NONFINITE_NUMBER")


def _regular_file(path: Path, code: str) -> Path:
    try:
        info = path.lstat()
    except (FileNotFoundError, OSError):
        raise VideoSemanticsCLIError(code) from None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise VideoSemanticsCLIError(code)
    return path


def _read_json(path: Path) -> Any:
    _regular_file(path, "INPUT_NOT_REGULAR")
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except VideoSemanticsCLIError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise VideoSemanticsCLIError("INPUT_JSON_INVALID") from None


def _read_text(path: Path) -> str:
    _regular_file(path, "INPUT_NOT_REGULAR")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise VideoSemanticsCLIError("INPUT_TEXT_INVALID") from None


def _output_dir(path: Path, operation: str) -> str:
    """Return one private-store namespace, never a caller-selected filesystem path."""

    value = path.as_posix()
    parts = path.parts
    expected_root = _OUTPUT_ROOT_BY_OPERATION[operation]
    if (
        path.is_absolute()
        or "\\" in value
        or len(parts) < 2
        or parts[0] != expected_root
        or any(part in {"", ".", ".."} for part in parts)
        or any(any(ord(char) < 0x20 for char in part) for part in parts)
    ):
        raise VideoSemanticsCLIError("OUTPUT_PRIVATE_NAMESPACE_REQUIRED")
    try:
        prepare_private_store()
    except VideoPrivateIOError:
        raise VideoSemanticsCLIError("OUTPUT_PRIVATE_STORE_BLOCKED") from None
    return "/".join(parts)


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _json_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise VideoSemanticsCLIError("OUTPUT_JSON_INVALID") from None


def _write_outputs(
    namespace: str,
    values: Mapping[str, Any],
    operation: str,
) -> list[dict[str, Any]]:
    names = list(values)
    if len(set(names)) != len(names) or any(Path(name).name != name for name in names):
        raise VideoSemanticsCLIError("OUTPUT_NAME_INVALID")
    encoded = {name: _json_bytes(value) for name, value in values.items()}
    records = [
        {"name": name, "bytes": len(encoded[name]), "sha256": _hash_bytes(encoded[name])}
        for name in names
    ]
    manifest = {
        "schema_version": 1,
        "operation": operation,
        "status": "VALID",
        "files": records,
        "payload_redacted": True,
    }
    try:
        for name in names:
            write_private_bytes_atomic(f"{namespace}/{name}", encoded[name])
        # This no-replace manifest is the commit marker. Payload files left by
        # an interrupted run are private orphans and never constitute a
        # published result without this final marker.
        manifest_name = "_bundle-manifest.json"
        manifest_bytes = _json_bytes(manifest)
        write_private_bytes_atomic(f"{namespace}/{manifest_name}", manifest_bytes)
    except VideoPrivateIOError:
        raise VideoSemanticsCLIError("OUTPUT_PRIVATE_WRITE_BLOCKED") from None
    return [
        *records,
        {
            "name": manifest_name,
            "bytes": len(manifest_bytes),
            "sha256": _hash_bytes(manifest_bytes),
        },
    ]


def _summary(operation: str, files: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": operation,
        "status": "VALID",
        "files": files,
        "payload_redacted": True,
    }


def _blocked(operation: str, code: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": operation,
        "status": "BLOCKED",
        "error_code": code,
        "payload_redacted": True,
    }


def _sequence(value: Any, *, key: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping) and isinstance(value.get(key), list):
        return value[key]
    raise VideoSemanticsCLIError("INPUT_ROSTER_INVALID")


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VideoSemanticsCLIError("INPUT_OBJECT_INVALID")
    return value


_EVALUATION_PIN_KEYS = frozenset(
    {
        "benchmark_revision",
        "oracle_revision",
        "semantic_source_revision",
        "constraint_revision",
        "grammar_revision",
        "toolchain_revision",
        "base_model_ref",
        "tokenizer_ref",
        "adapter_ref",
        "decoding_profile",
    }
)


def _evaluation_pins(value: Any, benchmark_revision: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _EVALUATION_PIN_KEYS:
        raise VideoSemanticsCLIError("INPUT_EVALUATION_PINS_REQUIRED")
    result = dict(value)
    for key in (
        "benchmark_revision",
        "oracle_revision",
        "semantic_source_revision",
        "constraint_revision",
        "grammar_revision",
        "toolchain_revision",
    ):
        if not isinstance(result[key], str) or HASH_RE.fullmatch(result[key]) is None:
            raise VideoSemanticsCLIError("INPUT_EVALUATION_PINS_INVALID")
    if result["benchmark_revision"] != benchmark_revision:
        raise VideoSemanticsCLIError("INPUT_EVALUATION_PINS_INVALID")
    for key in ("base_model_ref", "tokenizer_ref", "decoding_profile"):
        if not isinstance(result[key], str) or not result[key]:
            raise VideoSemanticsCLIError("INPUT_EVALUATION_PINS_INVALID")
    if result["adapter_ref"] is not None and (
        not isinstance(result["adapter_ref"], str) or not result["adapter_ref"]
    ):
        raise VideoSemanticsCLIError("INPUT_EVALUATION_PINS_INVALID")
    return result


def _benchmark_tasks(value: Any) -> list[Any]:
    if isinstance(value, Mapping) and isinstance(value.get("tasks"), Mapping):
        if (
            value.get("status") != "terminal"
            or not isinstance(value.get("terminal_manifest"), str)
            or HASH_RE.fullmatch(value["terminal_manifest"]) is None
            or value.get("model_outputs_present") is not False
        ):
            raise VideoSemanticsCLIError("INPUT_BENCHMARK_NOT_TERMINAL")
        tasks = value["tasks"]
        if isinstance(tasks.get("dev"), list) and isinstance(tasks.get("frozen"), list):
            # ``build_benchmark_freeze`` keeps the split in its envelope, not
            # in each task.  The paired evaluator requires it per task, so
            # make that one explicit, verified adaptation; never guess a split
            # for a bare task list.
            source_tasks = [*tasks["dev"], *tasks["frozen"]]
            if value.get("benchmark_revision") != benchmark_revision(source_tasks):
                raise VideoSemanticsCLIError("INPUT_BENCHMARK_REVISION_DRIFT")
            pins = _evaluation_pins(value.get("evaluation_pins"), value.get("benchmark_revision"))
            flattened: list[Any] = []
            for split in ("dev", "frozen"):
                for task in tasks[split]:
                    if not isinstance(task, Mapping):
                        raise VideoSemanticsCLIError("INPUT_TASK_ROSTER_INVALID")
                    if "split" in task and task["split"] != split:
                        raise VideoSemanticsCLIError("INPUT_TASK_SPLIT_MISMATCH")
                    item = dict(task)
                    provenance = item.get("provenance")
                    if not isinstance(provenance, Mapping):
                        raise VideoSemanticsCLIError("INPUT_TASK_ROSTER_INVALID")
                    expected = {
                        "semantic_source_revision": provenance.get("source_revision"),
                        "constraint_revision": provenance.get("constraint_revision"),
                        "grammar_revision": provenance.get("grammar_revision"),
                        "toolchain_revision": provenance.get("toolchain_revision"),
                        "base_model_ref": provenance.get("base_model_ref"),
                        "tokenizer_ref": provenance.get("tokenizer_ref"),
                        "adapter_ref": provenance.get("adapter_ref"),
                    }
                    if any(pins[key] != expected_value for key, expected_value in expected.items()):
                        raise VideoSemanticsCLIError("INPUT_TASK_PIN_DRIFT")
                    item["split"] = split
                    if "pins" in item and item["pins"] != pins:
                        raise VideoSemanticsCLIError("INPUT_TASK_PIN_DRIFT")
                    item["pins"] = pins
                    flattened.append(item)
            return flattened
    raise VideoSemanticsCLIError("INPUT_TASK_ROSTER_INVALID")


def execute_video_semantics(operation: str, args: Any) -> int:
    """Execute one offline operation and emit only its finite redacted summary."""

    if operation not in OFFLINE_OPERATIONS:
        raise ValueError(f"unsupported video semantics operation: {operation}")
    try:
        directory = _output_dir(Path(args.output_dir), operation)
        if operation == "normalize":
            describe = _read_json(Path(args.describe))
            values = [_read_json(Path(path)) for path in args.values]
            result = build_catalog_semantic_projection(
                _mapping(describe), values, catalog_ref=args.catalog_ref
            )
            if validate_catalog_projection_receipt(result["receipt"]):
                raise VideoSemanticsCLIError("PROJECTION_RECEIPT_INVALID")
            files = _write_outputs(
                directory,
                {
                    "projection.json": result["projection"],
                    "projection-receipt.json": result["receipt"],
                },
                operation,
            )
        elif operation == "census":
            result = build_local_census(
                _mapping(_read_json(Path(args.projection))),
                semantic_source_revision=args.semantic_source_revision,
                tenant_ref=getattr(args, "tenant_ref", None),
                catalog_ref=args.catalog_ref,
            )
            if validate_local_census_receipt(result["receipt"]):
                raise VideoSemanticsCLIError("CENSUS_RECEIPT_INVALID")
            files = _write_outputs(
                directory,
                {"census.json": result, "census-receipt.json": result["receipt"]},
                operation,
            )
        elif operation == "index":
            snapshot: Any = args.tenant_snapshot
            if args.tenant_snapshot_file is not None:
                snapshot = _read_json(Path(args.tenant_snapshot_file))
            result = build_semantic_index(
                _mapping(_read_json(Path(args.projection))),
                semantic_source_revision=args.semantic_source_revision,
                grammar_revision=args.grammar_revision,
                toolchain_revision=args.toolchain_revision,
                tenant_snapshot=snapshot,
            )
            if validate_semantic_index_receipt(result["receipt"]):
                raise VideoSemanticsCLIError("INDEX_RECEIPT_INVALID")
            files = _write_outputs(
                directory,
                {"index.json": result["index"], "index-receipt.json": result["receipt"]},
                operation,
            )
        elif operation == "ground":
            result = ground_request(
                _mapping(_read_json(Path(args.index))),
                _read_text(Path(args.request)),
                catalog=args.catalog,
            )
            if validate_grounding_receipt(result["receipt"]):
                raise VideoSemanticsCLIError("GROUNDING_RECEIPT_INVALID")
            files = _write_outputs(
                directory,
                {
                    "grounding.json": result["grounding"],
                    "grounding-receipt.json": result["receipt"],
                },
                operation,
            )
        elif operation == "evaluate":
            tasks = _benchmark_tasks(_read_json(Path(args.tasks)))
            observations = _sequence(_read_json(Path(args.observations)), key="observations")
            result = evaluate_paired_observations(tasks, observations)
            files = _write_outputs(directory, {"evaluation.json": result}, operation)
        else:
            benchmark = _mapping(_read_json(Path(args.benchmark)))
            thresholds = _mapping(_read_json(Path(args.thresholds)))
            receipts = _mapping(_read_json(Path(args.gate_receipts)))
            scorecard_input = _mapping(_read_json(Path(args.scorecards)))
            result = decide_weight_verdict(
                benchmark=benchmark,
                thresholds=thresholds,
                gate_receipts=receipts,
                scorecards=scorecard_input,
                contract_changed=args.contract_changed,
                new_structural_family=args.new_structural_family,
                delta_attempted=args.delta_attempted,
            )
            files = _write_outputs(directory, {"weight-verdict.json": result}, operation)
            if result["verdict"] == "BLOCKED":
                blocked = _blocked(operation, "WEIGHT_VERDICT_BLOCKED")
                blocked["files"] = files
                print(json.dumps(blocked, sort_keys=True))
                return 1
        print(json.dumps(_summary(operation, files), sort_keys=True))
        return 0
    except VideoSemanticsCLIError as error:
        print(json.dumps(_blocked(operation, error.code), sort_keys=True))
        return 1
    except Exception:
        # Do not serialize exception text: parser errors can contain literals,
        # paths, requests, or upstream payload fragments.
        print(json.dumps(_blocked(operation, "OFFLINE_OPERATION_BLOCKED"), sort_keys=True))
        return 1


__all__ = ["OFFLINE_OPERATIONS", "VideoSemanticsCLIError", "execute_video_semantics"]
