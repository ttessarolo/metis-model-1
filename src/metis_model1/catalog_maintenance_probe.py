"""Fail-closed catalog-maintenance probe executor.

This lane is deliberately separate from the historical endpoint Oracle.  The
probe evaluates catalog sources through the pinned ``catalog-domain.ts``
``describe`` path, with public-synthetic per-field retrieval only for the one
case which explicitly requests it.  Freeze is a pre-output operation; run
starts the local adapter-off worker only after all Git, pin, retrieval, and
checkpoint identities have been revalidated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

from metis_model1 import catalog_maintenance_pin as pin
from metis_model1.catalog_retrieval import adapt_catalog_retrieval_response
from metis_model1.catalog_retrieval_refresh import (
    CatalogQuery,
    _fixture_records,
    _pinned_snapshot,
    _stable_bytes,
    pin_module_parse_response,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROBE_MANIFEST = PROJECT_ROOT / "manifests/catalog-maintenance-probe-v1.json"
PROBE_SCHEMA = PROJECT_ROOT / "schemas/catalog-maintenance-probe.schema.json"
FREEZE_SCHEMA = PROJECT_ROOT / "schemas/catalog-maintenance-probe-freeze.schema.json"
FREEZE_OUTPUT = PROJECT_ROOT / "manifests/catalog-maintenance-probe-freeze-v1.json"
RETRIEVAL_MANIFEST = PROJECT_ROOT / "manifests/catalog-retrieval-public-synthetic-v1.json"
RETRIEVAL_RECEIPT = PROJECT_ROOT / "manifests/catalog-retrieval-execution-v1.json"
RETRIEVAL_SCHEMA = PROJECT_ROOT / "schemas/catalog-retrieval-execution-receipt.schema.json"
DELIVERY_ROOT = PROJECT_ROOT / "artifacts/w5-xs/2026-08-24-delivery"
DEFAULT_METIS_ROOT = Path("/Users/tommasotessarolo/Developer/ares-matioska/metis")
DEFAULT_NODE: Path | None = None
DEFAULT_MODEL = PROJECT_ROOT / "artifacts/w4/2026-08-20-qualification/checkpoint"
DEFAULT_CHECKPOINT_REPORT = DELIVERY_ROOT / "preflight/checkpoint-verification.json"
DEFAULT_WORKER = DELIVERY_ROOT / "w5_xs_inference_worker.py"
DEFAULT_WORKER_PYTHON = PROJECT_ROOT / "qualification/.venv/bin/python"
CATALOG_FIXTURE = PROJECT_ROOT / "fixtures/catalog-maintenance/public-synthetic-v1"
PROBE_MANIFEST_SHA256 = "sha256:e3c1280085995f8eb14012cfa8b0a0b787609d6a47ed2c04eb254a22358be24f"
PROBE_SCHEMA_SHA256 = "sha256:4440d8ffcfaf65fd7f0ba25aab820a4b19a8cc5cf6dc67040bc63e8e4cf31b4e"
RETRIEVAL_MANIFEST_SHA256 = (
    "sha256:203ed68a1574c869910fc0b096cfa3a760a3e0b6857a9fb89d1902d582241bb2"
)
RETRIEVAL_RECEIPT_SHA256 = "sha256:dd5a2b3046842dba35bffd06111882caafe52c66d80bd1f0d3b7c3a7d911ea5b"
RETRIEVAL_SCHEMA_SHA256 = "sha256:22d90adf2ad28eaaf81285dccbd29058311573c1e8dd71bac4fd3c2edf0e8046"
FREEZE_SCHEMA_SHA256 = "sha256:3072cb821a30390f6a2610fb86de2aa44ca37898a7aeea23d9583b4ba07b5647"
PROBE_MANIFEST_FILE_SHA256 = (
    "sha256:f9b53a7868e07155153052cd80e936e6c7dadea4a0afb71f3898f7aa00be4046"
)
RETRIEVAL_RECEIPT_SELF_SHA256 = (
    "sha256:6d007c933ffa9ec4c672b007538c6146b33b19e415174ef474dfc96f455f360d"
)
CHECKPOINT_REVISION = "3e6447f082e89cc7f0bc6e5441afd38dfce760ff"
MAX_MODEL_METAL_GB = 110.0
MAX_WALL_SECONDS = 4 * 60 * 60
MAX_CASE_BYTES = 256 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
SOURCE_RE = re.compile(r"```(?:metis)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
INLINE_VALUES_RE = re.compile(r"\bvalues\s*\[")
EXPECTED_WEIGHT_FILES = {
    "model-00001-of-00003.safetensors",
    "model-00002-of-00003.safetensors",
    "model-00003-of-00003.safetensors",
}
PUBLIC_FIXTURE_PATHS = (
    "fixtures/catalog-maintenance/public-synthetic-v1/catalogs/aa-video.metis",
    "fixtures/catalog-maintenance/public-synthetic-v1/catalogs/bb-people.metis",
    "fixtures/catalog-maintenance/public-synthetic-v1/metis.toml",
    "fixtures/catalog-maintenance/public-synthetic-v1/values/aa-list.metis",
    "fixtures/catalog-maintenance/public-synthetic-v1/values/bb-reflected.metis",
    "fixtures/catalog-maintenance/public-synthetic-v1/values/cc-editorial.metis",
)
MAX_WORKER_READY_SECONDS = 30 * 60
MAX_WORKER_RESPONSE_SECONDS = 20 * 60
NONCLAIMS = [
    "no_accuracy_claim",
    "no_promotion_claim",
    "no_training_authority",
    "no_tenant_dataset_authority",
    "no_independent_accuracy_denominator",
    "no_live_execution_attestation",
    "nonpromotable",
]
_ACTIVE_DESCRIBE_SNAPSHOT: Any | None = None


class CatalogMaintenanceProbeError(RuntimeError):
    """Raised when the maintenance probe cannot satisfy its fixed contract."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def raw_hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _file_hash(path: Path, label: str, maximum: int) -> tuple[int, str]:
    """Hash a bounded regular file without materializing large weights."""

    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        opened = os.fstat(descriptor)
        if not (opened.st_mode & 0o170000) == 0o100000 or opened.st_nlink != 1:
            raise CatalogMaintenanceProbeError(f"{label} is not a regular file")
        if opened.st_size > maximum:
            raise CatalogMaintenanceProbeError(f"{label} exceeds its byte cap")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
        path_after = path.lstat()
    except OSError as error:
        raise CatalogMaintenanceProbeError(f"{label} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)

    def identity(value: os.stat_result) -> tuple[int, ...]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    if (
        identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(path_after)
        or total != before.st_size
    ):
        raise CatalogMaintenanceProbeError(f"{label} changed while hashed")
    return total, "sha256:" + digest.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path = path.resolve(strict=False)
    if any(
        parent.is_symlink()
        for parent in (path.parent, *path.parent.parents)
        if parent.exists() and parent != PROJECT_ROOT.parent
    ):
        raise CatalogMaintenanceProbeError(f"output path crosses a symlink: {path}")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        raise CatalogMaintenanceProbeError("temporary output already exists")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _load_json(path: Path, label: str, *, maximum: int = MAX_CASE_BYTES) -> tuple[Any, bytes]:
    raw = _stable_bytes(path.resolve(strict=True), label, maximum)
    try:
        return json.loads(raw.decode("utf-8")), raw
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogMaintenanceProbeError(f"{label} is not valid JSON") from error


def _schema(path: Path, expected: str, label: str) -> dict[str, Any]:
    value, raw = _load_json(path, label)
    if raw_hash(raw) != expected:
        raise CatalogMaintenanceProbeError(f"{label} differs from its fixed digest")
    if not isinstance(value, dict):
        raise CatalogMaintenanceProbeError(f"{label} must be an object")
    try:
        Draft202012Validator.check_schema(value)
    except Exception as error:  # noqa: BLE001
        raise CatalogMaintenanceProbeError(f"{label} is not a valid JSON schema") from error
    return value


def _validate(value: Any, schema: Mapping[str, Any], label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise CatalogMaintenanceProbeError(
            f"{label} schema mismatch at {location}: {first.message}"
        )


def load_probe_contract(
    root: Path = PROJECT_ROOT,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    manifest, manifest_raw = _load_json(
        root / PROBE_MANIFEST.relative_to(PROJECT_ROOT), "probe manifest"
    )
    if (
        not isinstance(manifest, dict)
        or raw_hash(manifest_raw) != PROBE_MANIFEST_FILE_SHA256
        or manifest.get("manifest_sha256")
        != canonical_hash(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        )
        or manifest.get("manifest_sha256") != PROBE_MANIFEST_SHA256
    ):
        raise CatalogMaintenanceProbeError("probe manifest differs from its fixed digest")
    schema = _schema(
        root / PROBE_SCHEMA.relative_to(PROJECT_ROOT), PROBE_SCHEMA_SHA256, "probe schema"
    )
    _validate(manifest, schema, "probe manifest")
    if not isinstance(manifest, dict):
        raise CatalogMaintenanceProbeError("probe manifest must be an object")
    case_schema = schema.get("$defs", {}).get("case")
    if not isinstance(case_schema, dict):
        raise CatalogMaintenanceProbeError("probe schema does not define the case contract")
    cases: list[dict[str, Any]] = []
    for descriptor in manifest["cases"]:
        case_path = root / descriptor["fixture_path"]
        case, case_raw = _load_json(case_path, f"case {descriptor['case_id']}")
        expected = next(
            item for item in manifest["files"] if item["path"] == descriptor["fixture_path"]
        )
        if len(case_raw) != expected["bytes"] or raw_hash(case_raw) != expected["sha256"]:
            raise CatalogMaintenanceProbeError(f"case hash drift: {descriptor['case_id']}")
        _validate(case, case_schema, f"case {descriptor['case_id']}")
        if not isinstance(case, dict) or case.get("case_id") != descriptor["case_id"]:
            raise CatalogMaintenanceProbeError(f"case identity drift: {descriptor['case_id']}")
        cases.append(case)
    if len(cases) != 8 or len({case["case_id"] for case in cases}) != 8:
        raise CatalogMaintenanceProbeError("probe must contain 8 distinct cases")
    return manifest, schema, cases


def _git(project: Path, *args: str, check: bool = True) -> str:
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    try:
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(project), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CatalogMaintenanceProbeError(f"Git command failed: {' '.join(args)}") from error
    if check and result.returncode != 0:
        raise CatalogMaintenanceProbeError(f"Git command failed: {' '.join(args)}")
    return result.stdout.strip()


def current_remote_ref(project: Path, remote: str, remote_ref: str | None) -> str:
    if remote_ref:
        return remote_ref
    branch = _git(project, "symbolic-ref", "--short", "HEAD")
    if not branch or branch == "HEAD":
        raise CatalogMaintenanceProbeError("detached HEAD requires --remote-ref")
    return f"refs/heads/{branch}"


def require_head_published(project: Path, remote: str, remote_ref: str) -> tuple[str, str]:
    head = _git(project, "rev-parse", "HEAD")
    rows = _git(project, "ls-remote", remote, remote_ref).splitlines()
    if len(rows) != 1:
        raise CatalogMaintenanceProbeError("remote/ref did not return exactly one revision")
    parts = rows[0].split()
    if len(parts) != 2 or parts[1] != remote_ref or parts[0] != head:
        raise CatalogMaintenanceProbeError("current HEAD is not exactly published to remote/ref")
    return head, _git(project, "rev-parse", "HEAD^{tree}")


def _git_blob(project: Path, path: str, revision: str = "HEAD") -> str:
    try:
        raw = subprocess.check_output(
            ["/usr/bin/git", "-C", str(project), "show", f"{revision}:{path}"], timeout=60
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CatalogMaintenanceProbeError(f"bound input is not committed: {path}") from error
    return raw_hash(raw)


def _bound_paths(manifest: Mapping[str, Any]) -> list[str]:
    return [
        "manifests/catalog-maintenance-probe-v1.json",
        "schemas/catalog-maintenance-probe.schema.json",
        "schemas/catalog-maintenance-probe-freeze.schema.json",
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
        *PUBLIC_FIXTURE_PATHS,
        *[item["path"] for item in manifest["files"]],
    ]


def _bound_input_records(project: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in _bound_paths(manifest):
        raw = subprocess.check_output(
            ["/usr/bin/git", "-C", str(project), "show", f"HEAD:{path}"], timeout=60
        )
        tree_row = _git(project, "ls-tree", "HEAD", "--", path).split()
        if len(tree_row) != 4 or tree_row[1] != "blob" or tree_row[3] != path:
            raise CatalogMaintenanceProbeError(f"bound input is not one committed blob: {path}")
        records.append(
            {
                "path": path,
                "bytes": len(raw),
                "sha256": raw_hash(raw),
                "git_blob_oid": tree_row[2],
            }
        )
    return records


def _require_bound_worktree_matches_head(project: Path, records: list[Mapping[str, Any]]) -> None:
    """Reject a dirty or swapped bound input before sealing or execution."""

    for record in records:
        path = project / str(record["path"])
        size, digest = _file_hash(path, f"bound input {record['path']}", 64 * 1024 * 1024)
        if size != record["bytes"] or digest != record["sha256"]:
            raise CatalogMaintenanceProbeError(
                f"bound worktree input differs from HEAD: {record['path']}"
            )


def _runtime_identity(path: Path, label: str) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    size, digest = _file_hash(resolved, label, 16 * 1024**3)
    return {"path": str(resolved), "bytes": size, "sha256": digest}


def _python_runtime_identity(path: Path) -> dict[str, Any]:
    """Bind the venv launcher without resolving away its environment semantics."""

    invocation = path if path.is_absolute() else (PROJECT_ROOT / path)
    invocation = invocation.absolute()
    before = invocation.lstat()
    if not (invocation.is_symlink() or invocation.is_file()):
        raise CatalogMaintenanceProbeError("worker Python launcher is not a file or symlink")
    target = invocation.resolve(strict=True)
    target_size, target_digest = _file_hash(target, "worker Python target", 1024**3)
    script = (
        "import importlib.metadata as m,json,sys;"
        "print(json.dumps({'python_version':sys.version.split()[0],"
        "'sys_prefix':sys.prefix,'mlx':m.version('mlx'),"
        "'mlx_vlm':m.version('mlx-vlm')},sort_keys=True))"
    )
    try:
        completed = subprocess.run(
            [str(invocation), "-I", "-c", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
        metadata = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise CatalogMaintenanceProbeError("worker Python environment is unavailable") from error
    if completed.returncode != 0 or not isinstance(metadata, dict):
        raise CatalogMaintenanceProbeError("worker Python environment probe failed")
    expected = {"python_version": "3.12.10", "mlx": "0.32.1", "mlx_vlm": "0.6.15"}
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise CatalogMaintenanceProbeError("worker Python package versions contain drift")
    prefix = Path(str(metadata.get("sys_prefix", ""))).resolve(strict=True)
    if prefix != (PROJECT_ROOT / "qualification/.venv").resolve(strict=True):
        raise CatalogMaintenanceProbeError("worker Python is not the qualification virtualenv")
    after = invocation.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    if tuple(getattr(before, field) for field in fields) != tuple(
        getattr(after, field) for field in fields
    ):
        raise CatalogMaintenanceProbeError("worker Python launcher changed while identified")
    return {
        "invocation_path": str(invocation),
        "invocation_link_target": os.readlink(invocation) if invocation.is_symlink() else None,
        "invocation_device": after.st_dev,
        "invocation_inode": after.st_ino,
        "invocation_mtime_ns": after.st_mtime_ns,
        "invocation_ctime_ns": after.st_ctime_ns,
        "target_path": str(target),
        "target_bytes": target_size,
        "target_sha256": target_digest,
        **metadata,
    }


def _node_argument(value: Path | None) -> Path:
    if value is not None:
        return value.resolve(strict=True)
    discovered = shutil.which("node")
    if not discovered:
        raise CatalogMaintenanceProbeError("no Node executable found; pass --node-path")
    return Path(discovered).resolve(strict=True)


def _retrieval_contract(
    root: Path = PROJECT_ROOT,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    retrieval_manifest, retrieval_manifest_raw = _load_json(
        root / RETRIEVAL_MANIFEST.relative_to(PROJECT_ROOT), "retrieval manifest"
    )
    receipt, receipt_raw = _load_json(
        root / RETRIEVAL_RECEIPT.relative_to(PROJECT_ROOT), "retrieval receipt"
    )
    _schema(
        root / RETRIEVAL_SCHEMA.relative_to(PROJECT_ROOT),
        RETRIEVAL_SCHEMA_SHA256,
        "retrieval schema",
    )
    if (
        raw_hash(retrieval_manifest_raw) != RETRIEVAL_MANIFEST_SHA256
        or raw_hash(receipt_raw) != RETRIEVAL_RECEIPT_SHA256
    ):
        raise CatalogMaintenanceProbeError("retrieval contract digest drift")
    errors = pin.validate_catalog_maintenance_pin_contract(root)
    if errors:
        raise CatalogMaintenanceProbeError("catalog pin contract failed: " + "; ".join(errors))
    if not isinstance(retrieval_manifest, dict) or not isinstance(receipt, dict):
        raise CatalogMaintenanceProbeError("retrieval contracts must be objects")
    if receipt.get("upstream", {}).get("revision") != "5e112f9148f40e7e792052e896c5a9efe8eaf0a2":
        raise CatalogMaintenanceProbeError("retrieval receipt uses the wrong catalog pin")
    if receipt.get("receipt_sha256") != RETRIEVAL_RECEIPT_SELF_SHA256:
        raise CatalogMaintenanceProbeError("retrieval receipt self-hash drift")
    return retrieval_manifest, receipt, pin.load_catalog_maintenance_pin(root)


def _checkpoint_file_record(path: Path, label: str, maximum: int) -> dict[str, Any]:
    before = path.lstat()
    size, digest = _file_hash(path, label, maximum)
    after = path.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    if tuple(getattr(before, field) for field in fields) != tuple(
        getattr(after, field) for field in fields
    ):
        raise CatalogMaintenanceProbeError(f"{label} changed while identified")
    return {
        "path": path.name,
        "bytes": size,
        "sha256": digest,
        "device": after.st_dev,
        "inode": after.st_ino,
        "mtime_ns": after.st_mtime_ns,
        "ctime_ns": after.st_ctime_ns,
    }


def _safe_checkpoint_weight_name(value: Any) -> str:
    if not isinstance(value, str):
        raise CatalogMaintenanceProbeError("checkpoint weight path is not a string")
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) != 1 or path.name != value:
        raise CatalogMaintenanceProbeError("checkpoint weight path escapes the checkpoint")
    return value


def _checkpoint_identity(model_path: Path, report_path: Path) -> dict[str, Any]:
    report, report_raw = _load_json(report_path, "checkpoint report", maximum=4 * 1024 * 1024)
    if (
        not isinstance(report, dict)
        or report.get("status") != "verified"
        or report.get("revision") != CHECKPOINT_REVISION
    ):
        raise CatalogMaintenanceProbeError(
            "checkpoint report is not the verified frozen checkpoint"
        )
    model = model_path.resolve(strict=True)
    if not model.is_dir():
        raise CatalogMaintenanceProbeError("checkpoint path is not a directory")
    if Path(str(report.get("checkpoint_path", ""))).resolve() != model:
        raise CatalogMaintenanceProbeError("checkpoint report does not bind model path")
    all_entries = sorted(model.iterdir(), key=lambda item: item.name)
    if not all_entries or any(entry.is_symlink() for entry in all_entries):
        raise CatalogMaintenanceProbeError("checkpoint contains a symlink or is empty")
    directories = [entry for entry in all_entries if entry.is_dir()]
    if [entry.name for entry in directories] != [".cache"]:
        raise CatalogMaintenanceProbeError(
            "checkpoint directories differ from the excluded download cache"
        )
    entries = [entry for entry in all_entries if entry.name != ".cache"]
    if not entries or any(not entry.is_file() for entry in entries):
        raise CatalogMaintenanceProbeError("checkpoint payload must be direct regular files")
    names = {entry.name for entry in entries}
    weights: list[dict[str, Any]] = []
    reported_weight_names: set[str] = set()
    for item in report.get("weight_files", []):
        if not isinstance(item, dict) or set(item) != {"bytes", "path", "sha256"}:
            raise CatalogMaintenanceProbeError("checkpoint weight roster is invalid")
        name = _safe_checkpoint_weight_name(item["path"])
        if name in reported_weight_names:
            raise CatalogMaintenanceProbeError("checkpoint weight roster contains duplicates")
        reported_weight_names.add(name)
        record = _checkpoint_file_record(model / name, f"checkpoint weight {name}", 8 * 1024**3)
        if record["bytes"] != item["bytes"] or record["sha256"] != "sha256:" + item["sha256"]:
            raise CatalogMaintenanceProbeError(f"checkpoint weight hash mismatch: {name}")
        weights.append(record)
    if reported_weight_names != EXPECTED_WEIGHT_FILES:
        raise CatalogMaintenanceProbeError("checkpoint weight roster is not the fixed three shards")
    if not EXPECTED_WEIGHT_FILES.issubset(names):
        raise CatalogMaintenanceProbeError("checkpoint weight payload is incomplete")
    auxiliary_files = [
        _checkpoint_file_record(entry, f"checkpoint auxiliary file {entry.name}", 1024**3)
        for entry in entries
        if entry.name not in EXPECTED_WEIGHT_FILES
    ]
    config_records = [record for record in auxiliary_files if record["path"] == "config.json"]
    if len(config_records) != 1:
        raise CatalogMaintenanceProbeError("checkpoint must contain exactly one config.json")
    config = config_records[0]
    if config["sha256"] != "sha256:" + str(report.get("config_sha256", "")):
        raise CatalogMaintenanceProbeError("checkpoint config hash mismatch")
    return {
        "path": str(model),
        "report_sha256": raw_hash(report_raw),
        "config_sha256": config["sha256"],
        "config_bytes": config["bytes"],
        "weights": weights,
        "auxiliary_files": auxiliary_files,
        "excluded_nonpayload_paths": [".cache"],
        "revision": CHECKPOINT_REVISION,
    }


def _require_checkpoint_metadata_unchanged(checkpoint: Mapping[str, Any]) -> None:
    """Detect any checkpoint mutation after the pre-run full hash and model load."""

    model = Path(str(checkpoint["path"])).resolve(strict=True)
    excluded = checkpoint.get("excluded_nonpayload_paths")
    if excluded != [".cache"]:
        raise CatalogMaintenanceProbeError("checkpoint cache exclusion contract changed")
    cache = model / ".cache"
    if cache.is_symlink() or not cache.is_dir():
        raise CatalogMaintenanceProbeError("checkpoint excluded cache path changed type")
    expected = {
        record["path"]: record
        for record in [*checkpoint["weights"], *checkpoint["auxiliary_files"]]
    }
    entries = sorted(
        (entry for entry in model.iterdir() if entry.name != ".cache"),
        key=lambda item: item.name,
    )
    if {entry.name for entry in entries} != set(expected):
        raise CatalogMaintenanceProbeError("checkpoint file roster changed after verification")
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise CatalogMaintenanceProbeError("checkpoint file type changed after verification")
        stat = entry.lstat()
        record = expected[entry.name]
        observed = {
            "bytes": stat.st_size,
            "device": stat.st_dev,
            "inode": stat.st_ino,
            "mtime_ns": stat.st_mtime_ns,
            "ctime_ns": stat.st_ctime_ns,
        }
        if any(observed[key] != record[key] for key in observed):
            raise CatalogMaintenanceProbeError(
                f"checkpoint changed after verification: {entry.name}"
            )


def _worker_sandbox_policy(checkpoint_path: Path) -> str:
    root = checkpoint_path.resolve(strict=True)
    cache = root / ".cache"
    return " ".join(
        (
            "(version 1)",
            "(allow default)",
            "(deny network*)",
            f"(deny file-write* (subpath {json.dumps(str(root))}))",
            f"(deny file-read* (subpath {json.dumps(str(cache))}))",
        )
    )


def _describe_normalized(parsed: Mapping[str, Any]) -> dict[str, Any]:
    catalogs = parsed.get("catalogs")
    if not isinstance(catalogs, list):
        raise CatalogMaintenanceProbeError("catalog:describe response has no catalogs")
    selected = [
        item for item in catalogs if isinstance(item, dict) and item.get("name") == "public.video"
    ]
    if len(selected) != 1:
        raise CatalogMaintenanceProbeError("catalog:describe did not return exactly public.video")
    return {"catalogs": selected}


def _fixture_hash(records: list[dict[str, Any]]) -> str:
    return canonical_hash({"fixture_id": "catalog-retrieval/public-synthetic-v1", "files": records})


def _candidate_fixture(snapshot: Any, source: str) -> None:
    catalogs = snapshot.fixture / "catalogs"
    for path in catalogs.glob("*.metis"):
        if path.name != "aa-video.metis":
            path.unlink()
    (catalogs / "aa-video.metis").write_text(source, encoding="utf-8")


def _describe_source_in_snapshot(
    snapshot: Any, source: str, *, root: Path = PROJECT_ROOT
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Describe one candidate in a minimal tenant inside one pinned snapshot."""

    metis_toml = (CATALOG_FIXTURE / "metis.toml").read_bytes()
    tenant_hash = raw_hash(metis_toml + source.encode("utf-8"))
    if snapshot.fixture.exists():
        shutil.rmtree(snapshot.fixture)
    catalogs = snapshot.fixture / "catalogs"
    catalogs.mkdir(parents=True)
    (snapshot.fixture / "metis.toml").write_bytes(metis_toml)
    (catalogs / "aa-video.metis").write_text(source, encoding="utf-8")
    query = CatalogQuery("probe-describe", "describe", "public.video", None, {})
    execution = snapshot.run(query)
    receipt = adapt_catalog_retrieval_response(
        "describe",
        execution.raw,
        tenant_input_sha256=tenant_hash,
        catalog="public.video",
        root=root,
    )
    parsed, _ = pin_module_parse_response(execution.raw)
    return _describe_normalized(parsed), receipt


def _run_describe_once(
    metis_root: Path, node_path: Path, source: str, *, root: Path = PROJECT_ROOT
) -> tuple[dict[str, Any], dict[str, Any]]:
    if _ACTIVE_DESCRIBE_SNAPSHOT is not None:
        return _describe_source_in_snapshot(_ACTIVE_DESCRIBE_SNAPSHOT, source, root=root)
    with _pinned_snapshot(metis_root, node_path) as snapshot:
        return _describe_source_in_snapshot(snapshot, source, root=root)


def _copy_public_fixture(
    source_root: Path, destination: Path, records: list[dict[str, Any]]
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for record in records:
        relative = Path(record["path"])
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = _stable_bytes(source_root / relative, f"fixture {record['path']}", 4 * 1024 * 1024)
        target.write_bytes(raw)


def _retrieval_curated(
    metis_root: Path, node_path: Path, *, root: Path = PROJECT_ROOT
) -> dict[str, Any]:
    manifest, _receipt, _pin_manifest = _retrieval_contract(root)
    records, _ = _fixture_records(CATALOG_FIXTURE, manifest)
    with _pinned_snapshot(metis_root, node_path) as snapshot:
        _copy_public_fixture(CATALOG_FIXTURE, snapshot.fixture, records)
        execution = snapshot.run(
            CatalogQuery("values-enum-editorial", "values", "video", "genre", {})
        )
        receipt = adapt_catalog_retrieval_response(
            "values",
            execution.raw,
            tenant_input_sha256=_fixture_hash(records),
            catalog="video",
            field="genre",
            root=root,
        )
        parsed, _ = pin_module_parse_response(execution.raw)
        expected = {"kind": "enum", "size": 1, "nature": "editorial", "value": "Curated"}
        if (
            parsed.get("kind") != expected["kind"]
            or parsed.get("size") != expected["size"]
            or parsed.get("nature") != expected["nature"]
            or parsed.get("values") != [expected["value"]]
        ):
            raise CatalogMaintenanceProbeError(
                "public-synthetic Curated retrieval did not match the fixed value contract"
            )
        return {**expected, "receipt_sha256": receipt["receipt_sha256"]}


def build_prompt(case: Mapping[str, Any], retrieval: Mapping[str, Any] | None = None) -> str:
    prompt = [
        (
            "You are Metis Model 1. Produce one complete Metis 0.43 catalog source "
            "file and nothing else."
        ),
        (
            "Use the catalog-domain contract: external bounded domains use keyword "
            "enum(N), open live-index domains use keyword open, and only tiny stable "
            "domains retain inline value lists. Never invent or materialize retrieved "
            "tenant values unless the request explicitly identifies the tiny stable "
            "inline case."
        ),
        f"Task family: {case['family']}.",
    ]
    prompt.append("User request:\n" + case["prompt"]["request"])
    if "before_source" in case["prompt"]:
        prompt.append("Current source:\n" + case["prompt"]["before_source"].rstrip())
    if retrieval is not None:
        prompt.append(
            "Verified public-synthetic retrieval: video.genre returned "
            f"{retrieval['value']} as an editorial enum of size {retrieval['size']}."
        )
    prompt.append("Return only the complete corrected Metis source.")
    result = "\n\n".join(prompt)
    target = case["target"]["expected_source"]
    if target.strip() in result:
        raise CatalogMaintenanceProbeError(f"target leakage in prompt: {case['case_id']}")
    return result


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


def score_candidate(
    case: Mapping[str, Any],
    source: str | None,
    normalized: Mapping[str, Any] | None,
    retrieval_error: str | None = None,
    expected_skeleton: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    forbidden = case["target"]["forbidden_fragments"]
    required = case["target"]["required_fragments"]
    forbidden_hits = [
        fragment for fragment in forbidden if source is not None and fragment in source
    ]
    required_missing = [
        fragment for fragment in required if source is None or fragment not in source
    ]
    legacy_inline = int(
        any("values" in item for item in forbidden_hits)
        and any("enum(" in item or " open" in item for item in required)
    )
    tiny_inline = case.get("construct") == "tiny_stable_inline"
    invented_values = int(
        source is not None and not tiny_inline and bool(INLINE_VALUES_RE.search(source))
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
    _manifest, _schema_value, cases = load_probe_contract()
    expected_roots = {case["case_id"]: case["provenance"]["semantic_root"] for case in cases}
    case_ids = [item.get("case_id") for item in observations]
    if len(case_ids) != len(set(case_ids)):
        raise CatalogMaintenanceProbeError("gate observations contain duplicate case IDs")
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
    verdict = (
        "NO_RETRAIN"
        if canonical_roster
        and counts["cases_in"] == 8
        and counts["cases_out"] == 8
        and counts["cases_distinct"] == 8
        and counts["gaps"] == 0
        and counts["semantic_correct"] == 8
        and all(
            counts[key] == 0
            for key in ("critical_failure", "invented_values", "legacy_inline", "retrieval_error")
        )
        else "DIAGNOSE"
    )
    compatible_failures = [
        item
        for item in observations
        if not item.get("semantic_correct")
        and not item.get("critical_failure")
        and not item.get("retrieval_error")
    ]
    eligible = int(
        len(compatible_failures) >= 3
        and len({item.get("root_id") for item in compatible_failures}) >= 2
    )
    return {
        "verdict": verdict,
        "counts": counts,
        "delta_qlora_eligible_note": bool(eligible),
        "training_authorized": False,
    }


def _freeze_body(args: argparse.Namespace) -> dict[str, Any]:
    manifest, _schema, cases = load_probe_contract()
    remote_ref = current_remote_ref(PROJECT_ROOT, args.remote, args.remote_ref)
    head, tree = require_head_published(PROJECT_ROOT, args.remote, remote_ref)
    bound = _bound_input_records(PROJECT_ROOT, manifest)
    _require_bound_worktree_matches_head(PROJECT_ROOT, bound)
    node_path = _node_argument(args.node_path)
    pin_report = pin.verify_catalog_maintenance_pin(Path(args.metis_root), node_path)
    retrieval_manifest, retrieval_receipt, pin_manifest = _retrieval_contract()
    checkpoint = _checkpoint_identity(Path(args.model_path), Path(args.checkpoint_report))
    sandbox_policy = _worker_sandbox_policy(Path(checkpoint["path"]))
    runtime = {
        "probe_runner": _runtime_identity(Path(__file__), "probe runner"),
        "worker_script": _runtime_identity(Path(args.worker_script), "worker script"),
        "worker_python": _python_runtime_identity(Path(args.worker_python)),
        "checkpoint_report": _runtime_identity(Path(args.checkpoint_report), "checkpoint report"),
        "sandbox_policy_sha256": raw_hash(sandbox_policy.encode("utf-8")),
    }
    retrieval_value = _retrieval_curated(Path(args.metis_root), node_path)
    tasks: list[dict[str, Any]] = []
    with _pinned_snapshot(Path(args.metis_root), node_path) as snapshot:
        for case in cases:
            retrieval = (
                retrieval_value if case["retrieval"]["kind"] == "public_synthetic_value" else None
            )
            prompt = build_prompt(case, retrieval)
            normalized, receipt = _describe_source_in_snapshot(
                snapshot, case["target"]["expected_source"]
            )
            tasks.append(
                {
                    "case_id": case["case_id"],
                    "family": case["family"],
                    "mode": case["mode"],
                    "root_id": case["provenance"]["semantic_root"],
                    "prompt": prompt,
                    "prompt_sha256": canonical_hash(prompt),
                    "expected_skeleton": normalized,
                    "expected_skeleton_sha256": canonical_hash(normalized),
                    "expected_describe_receipt_sha256": receipt["receipt_sha256"],
                    "retrieval": retrieval,
                    "model_output_observed": False,
                }
            )
    body = {
        "schema_version": 1,
        "freeze_id": "catalog-maintenance-probe-freeze/v1",
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
            "manifest_sha256": pin.manifest_sha256(pin_manifest),
            "verification": pin_report["status"],
        },
        "retrieval": {
            "manifest_sha256": RETRIEVAL_MANIFEST_SHA256,
            "receipt_file_sha256": RETRIEVAL_RECEIPT_SHA256,
            "receipt_self_sha256": RETRIEVAL_RECEIPT_SELF_SHA256,
            "queries": 8,
            "curated": retrieval_value,
        },
        "checkpoint": checkpoint,
        "runtime": runtime,
        "model": manifest["model"],
        "counts": {"cases_in": 8, "cases_out": 8, "cases_distinct": 8, "gaps": 0},
        "tasks": tasks,
        "model_outputs_observed": False,
        "training_authorized": False,
        "nonclaims": NONCLAIMS,
    }
    body["freeze_sha256"] = canonical_hash(body)
    return body


def freeze(args: argparse.Namespace) -> int:
    output = Path(args.freeze_output).resolve()
    if output != FREEZE_OUTPUT.resolve():
        raise CatalogMaintenanceProbeError("freeze output path is fixed in the repository")
    if output.exists():
        raise CatalogMaintenanceProbeError(f"freeze output already exists: {output}")
    if Path(args.run_dir).exists():
        raise CatalogMaintenanceProbeError(
            f"run output already exists: {Path(args.run_dir).resolve()}"
        )
    body = _freeze_body(args)
    freeze_schema = _schema(
        PROJECT_ROOT / FREEZE_SCHEMA.relative_to(PROJECT_ROOT),
        FREEZE_SCHEMA_SHA256,
        "freeze schema",
    )
    _validate(body, freeze_schema, "freeze manifest")
    output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(output, canonical_bytes(body) + b"\n")
    print(
        json.dumps(
            {"event": "freeze_complete", "freeze_sha256": body["freeze_sha256"], "cases": 8},
            sort_keys=True,
        )
    )
    return 0


def _read_worker_json(
    worker: subprocess.Popen[bytes],
    buffer: bytearray,
    *,
    deadline: float,
    label: str,
) -> dict[str, Any]:
    if worker.stdout is None:
        raise CatalogMaintenanceProbeError("worker stdout is unavailable")
    descriptor = worker.stdout.fileno()
    while True:
        newline = buffer.find(b"\n")
        if newline >= 0:
            raw = bytes(buffer[:newline])
            del buffer[: newline + 1]
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise CatalogMaintenanceProbeError(f"{label} is not valid JSON") from error
            if not isinstance(value, dict):
                raise CatalogMaintenanceProbeError(f"{label} is not an object")
            return value
        if len(buffer) > MAX_OUTPUT_BYTES:
            raise CatalogMaintenanceProbeError(f"{label} exceeds its byte cap")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CatalogMaintenanceProbeError(f"{label} timed out")
        readable, _, _ = select.select([descriptor], [], [], remaining)
        if not readable:
            raise CatalogMaintenanceProbeError(f"{label} timed out")
        chunk = os.read(descriptor, min(64 * 1024, MAX_OUTPUT_BYTES + 1 - len(buffer)))
        if not chunk:
            raise CatalogMaintenanceProbeError(f"worker exited before {label}")
        buffer.extend(chunk)


def _worker_request(
    worker: subprocess.Popen[bytes],
    buffer: bytearray,
    request_id: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    global_deadline: float,
) -> dict[str, Any]:
    if worker.stdin is None or worker.stdout is None:
        raise CatalogMaintenanceProbeError("worker pipes unavailable")
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
    ).encode("utf-8")
    worker.stdin.write(payload)
    worker.stdin.flush()
    response = _read_worker_json(
        worker,
        buffer,
        deadline=min(global_deadline, time.monotonic() + MAX_WORKER_RESPONSE_SECONDS),
        label="worker generation",
    )
    if response.get("event") != "generation" or response.get("request_id") != request_id:
        raise CatalogMaintenanceProbeError("worker response identity mismatch")
    if float(response.get("peak_metal_gb", 0)) > MAX_MODEL_METAL_GB:
        raise CatalogMaintenanceProbeError("Metal memory limit exceeded")
    return response


def run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    global_deadline = started + MAX_WALL_SECONDS
    freeze_path = Path(args.freeze_output).resolve(strict=True)
    if freeze_path != FREEZE_OUTPUT.resolve():
        raise CatalogMaintenanceProbeError("freeze input path is fixed in the repository")
    freeze, freeze_raw = _load_json(freeze_path, "freeze manifest", maximum=16 * 1024 * 1024)
    if not isinstance(freeze, dict) or freeze.get("freeze_sha256") != canonical_hash(
        {k: v for k, v in freeze.items() if k != "freeze_sha256"}
    ):
        raise CatalogMaintenanceProbeError("freeze seal mismatch")
    if (
        freeze.get("status") != "frozen_before_model_output"
        or freeze.get("model_outputs_observed") is not False
    ):
        raise CatalogMaintenanceProbeError("freeze is not executable")
    freeze_schema = _schema(
        PROJECT_ROOT / FREEZE_SCHEMA.relative_to(PROJECT_ROOT),
        FREEZE_SCHEMA_SHA256,
        "freeze schema",
    )
    _validate(freeze, freeze_schema, "freeze manifest")
    freeze_relative = freeze_path.relative_to(PROJECT_ROOT).as_posix()
    if _git_blob(PROJECT_ROOT, freeze_relative) != raw_hash(freeze_raw):
        raise CatalogMaintenanceProbeError("freeze manifest is not committed byte-for-byte at HEAD")
    remote_ref = freeze["remote_ref"]
    head, tree = require_head_published(PROJECT_ROOT, freeze["remote"], remote_ref)
    _git(PROJECT_ROOT, "merge-base", "--is-ancestor", freeze["preimage_commit"], head)
    manifest, _probe_schema, cases = load_probe_contract()
    bound = _bound_input_records(PROJECT_ROOT, manifest)
    _require_bound_worktree_matches_head(PROJECT_ROOT, bound)
    if bound != freeze["bound_inputs"]:
        raise CatalogMaintenanceProbeError("bound inputs changed after freeze")
    node_path = _node_argument(args.node_path)
    pin_report = pin.verify_catalog_maintenance_pin(Path(args.metis_root), node_path)
    if pin_report["status"] != "verified_local_cooperative":
        raise CatalogMaintenanceProbeError("catalog pin is not verified")
    _retrieval_contract()
    checkpoint = _checkpoint_identity(Path(args.model_path), Path(args.checkpoint_report))
    if checkpoint != freeze["checkpoint"]:
        raise CatalogMaintenanceProbeError("checkpoint identity changed after freeze")
    sandbox_policy = _worker_sandbox_policy(Path(checkpoint["path"]))
    runtime = {
        "probe_runner": _runtime_identity(Path(__file__), "probe runner"),
        "worker_script": _runtime_identity(Path(args.worker_script), "worker script"),
        "worker_python": _python_runtime_identity(Path(args.worker_python)),
        "checkpoint_report": _runtime_identity(Path(args.checkpoint_report), "checkpoint report"),
        "sandbox_policy_sha256": raw_hash(sandbox_policy.encode("utf-8")),
    }
    if runtime != freeze["runtime"]:
        raise CatalogMaintenanceProbeError("runtime identity changed after freeze")
    curated = _retrieval_curated(Path(args.metis_root), node_path)
    if freeze["retrieval"]["curated"] != curated:
        raise CatalogMaintenanceProbeError("frozen curated retrieval truth changed")
    task_by_id = {case["case_id"]: case for case in cases}
    if len(freeze["tasks"]) != 8 or {task["case_id"] for task in freeze["tasks"]} != set(
        task_by_id
    ):
        raise CatalogMaintenanceProbeError("freeze task roster is not the exact eight-case roster")
    if [task["case_id"] for task in freeze["tasks"]] != [case["case_id"] for case in cases]:
        raise CatalogMaintenanceProbeError("freeze task order is not the exact case order")
    with _pinned_snapshot(Path(args.metis_root), node_path) as snapshot:
        for frozen_task in freeze["tasks"]:
            case = task_by_id[frozen_task["case_id"]]
            if any(
                frozen_task[key] != expected
                for key, expected in (
                    ("family", case["family"]),
                    ("mode", case["mode"]),
                    ("root_id", case["provenance"]["semantic_root"]),
                )
            ):
                raise CatalogMaintenanceProbeError(f"frozen case identity drift: {case['case_id']}")
            retrieval = curated if case["retrieval"]["kind"] == "public_synthetic_value" else None
            prompt = build_prompt(case, retrieval)
            if (
                frozen_task["prompt_sha256"] != canonical_hash(prompt)
                or frozen_task["prompt"] != prompt
            ):
                raise CatalogMaintenanceProbeError(f"frozen prompt drift: {case['case_id']}")
            normalized, receipt = _describe_source_in_snapshot(
                snapshot, case["target"]["expected_source"]
            )
            if (
                frozen_task["expected_skeleton_sha256"] != canonical_hash(normalized)
                or frozen_task["expected_skeleton"] != normalized
            ):
                raise CatalogMaintenanceProbeError(f"frozen truth drift: {case['case_id']}")
            if frozen_task["expected_describe_receipt_sha256"] != receipt["receipt_sha256"]:
                raise CatalogMaintenanceProbeError(
                    f"frozen oracle receipt drift: {case['case_id']}"
                )
    output_dir = Path(args.run_dir).resolve()
    if output_dir.exists():
        raise CatalogMaintenanceProbeError(f"run output already exists: {output_dir}")
    try:
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
    except ValueError:
        ignored = False
    if not ignored or not output_dir.is_relative_to(PROJECT_ROOT / "artifacts"):
        raise CatalogMaintenanceProbeError("run output must be under ignored artifacts")
    output_dir.mkdir(parents=True)
    worker_script = Path(args.worker_script).resolve(strict=True)
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
    command = [
        "/usr/bin/sandbox-exec",
        "-p",
        sandbox_policy,
        runtime["worker_python"]["invocation_path"],
        str(worker_script),
        "--model-path",
        str(checkpoint["path"]),
        "--checkpoint-report",
        str(Path(args.checkpoint_report).resolve(strict=True)),
    ]
    observations: list[dict[str, Any]] = []
    global _ACTIVE_DESCRIBE_SNAPSHOT
    snapshot_context = _pinned_snapshot(Path(args.metis_root), node_path)
    describe_snapshot = snapshot_context.__enter__()
    _ACTIVE_DESCRIBE_SNAPSHOT = describe_snapshot
    try:
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
            worker_buffer = bytearray()
            try:
                ready = _read_worker_json(
                    worker,
                    worker_buffer,
                    deadline=min(global_deadline, time.monotonic() + MAX_WORKER_READY_SECONDS),
                    label="worker readiness",
                )
                if (
                    ready.get("event") != "ready"
                    or ready.get("model_type") != "qwen3_5"
                    or ready.get("checkpoint_revision") != CHECKPOINT_REVISION
                ):
                    raise CatalogMaintenanceProbeError("worker readiness identity mismatch")
                _require_checkpoint_metadata_unchanged(checkpoint)
                for case, frozen_task in zip(cases, freeze["tasks"], strict=True):
                    if time.monotonic() >= global_deadline:
                        raise CatalogMaintenanceProbeError("four-hour wall-clock limit exceeded")
                    messages = [{"role": "user", "content": frozen_task["prompt"]}]
                    attempts: list[dict[str, Any]] = []
                    current = messages
                    final = None
                    for index in range(manifest["model"]["max_repair_cycles"] + 1):
                        response = _worker_request(
                            worker,
                            worker_buffer,
                            f"{case['case_id']}:{index}",
                            current,
                            manifest["model"]["max_tokens"],
                            global_deadline,
                        )
                        _require_checkpoint_metadata_unchanged(checkpoint)
                        source, extraction_error = _extract_source(response.get("text", ""))
                        normalized = None
                        retrieval_error = extraction_error
                        receipt_sha = None
                        if source is not None:
                            try:
                                normalized, receipt = _run_describe_once(
                                    Path(args.metis_root), node_path, source
                                )
                                receipt_sha = receipt["receipt_sha256"]
                                retrieval_error = None
                            except Exception:  # noqa: BLE001 - diagnostic is intentionally generic
                                retrieval_error = "catalog describe rejected candidate"
                        score = score_candidate(
                            case,
                            source,
                            normalized,
                            retrieval_error,
                            frozen_task["expected_skeleton"],
                        )
                        attempts.append(
                            {
                                "attempt": index,
                                "text": response.get("text", ""),
                                "text_sha256": raw_hash(str(response.get("text", "")).encode()),
                                "receipt_sha256": receipt_sha,
                                "score": score,
                            }
                        )
                        final = score
                        if score["semantic_correct"]:
                            break
                        current = messages + [
                            {"role": "assistant", "content": response.get("text", "")},
                            {
                                "role": "user",
                                "content": (
                                    "The candidate was rejected. Repair only using the "
                                    "following non-truth-leaking diagnostic: "
                                    "catalog:describe did not match the required catalog "
                                    "skeleton. Return the complete Metis 0.43 source only."
                                ),
                            },
                        ]
                    task_dir = output_dir / "tasks" / case["case_id"]
                    task_dir.mkdir(parents=True)
                    _atomic_write(task_dir / "attempts.json", canonical_bytes(attempts) + b"\n")
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
                    raise CatalogMaintenanceProbeError("worker shutdown timed out") from error
                if worker.returncode != 0:
                    raise CatalogMaintenanceProbeError("worker exited non-zero")
    finally:
        _ACTIVE_DESCRIBE_SNAPSHOT = None
        snapshot_context.__exit__(None, None, None)
    decision = gate_arithmetic(observations)
    report = {
        "schema_version": 1,
        "status": "complete",
        "head": head,
        "tree": tree,
        "freeze_sha256": freeze["freeze_sha256"],
        "observations": observations,
        "decision": decision,
        "model_outputs_observed": True,
        "training_authorized": False,
    }
    _atomic_write(output_dir / "report.json", canonical_bytes(report) + b"\n")
    print(
        json.dumps(
            {
                "event": "probe_complete",
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
    result.add_argument(
        "--run-dir", type=Path, default=PROJECT_ROOT / "artifacts/catalog-maintenance-probe-v1"
    )
    result.add_argument("--remote", default="origin")
    result.add_argument("--remote-ref", default=None)
    result.add_argument("--metis-root", type=Path, default=DEFAULT_METIS_ROOT)
    result.add_argument("--node-path", type=Path, default=DEFAULT_NODE)
    result.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    result.add_argument("--checkpoint-report", type=Path, default=DEFAULT_CHECKPOINT_REPORT)
    result.add_argument("--worker-script", type=Path, default=DEFAULT_WORKER)
    result.add_argument("--worker-python", type=Path, default=DEFAULT_WORKER_PYTHON)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return freeze(args) if args.mode == "freeze" else run(args)
    except Exception as error:
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
