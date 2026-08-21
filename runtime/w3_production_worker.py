#!/usr/bin/env python3
"""One-shot production-capsule worker for the W3 F-1/F-2/F-3 smoke bridge.

The worker is intentionally subordinate to ``w3_qualifier.py``.  It accepts a
fully reconstructed execution roster, calls only the low-level immutable
capsule boundary evidence produced by the outer supervisor, and writes only
below the process/output roots supplied by that launcher.  It has no process
creation path and never accepts a live Metis checkout path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from metis_model1.oracles import (
    OracleError,
    normalize_capsule_oracle_envelope,
    verify_capsule_oracle_envelope,
)

PROTOCOL = "w3-production-capsule-worker-v2"
SCHEMA_VERSION = 2
HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ROLE_COUNTS = {"author": 1, "before": 1, "after": 1, "mutated": 1, "fixed": 1}
ROLE_FAMILY = {
    "author": "F-1",
    "before": "F-2",
    "after": "F-2",
    "mutated": "F-3",
    "fixed": "F-3",
}
ROLE_EXPECTED_STATUS = {
    "author": "ok",
    "before": "ok",
    "after": "ok",
    "mutated": "invalid",
    "fixed": "ok",
}
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


class ProductionWorkerError(ValueError):
    """Base typed failure for the isolated production worker."""

    kind = "worker-input"


class ProductionWorkerTrustError(ProductionWorkerError):
    kind = "worker-trust"


class ProductionWorkerExecutionError(ProductionWorkerError):
    kind = "worker-execution"


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    except (TypeError, ValueError, RecursionError) as error:
        raise ProductionWorkerError("value is not canonical JSON") from error


def _sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _bytes_sha(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ProductionWorkerError(f"{label} does not have the exact registered fields")
    return value


def _exact_int(value: Any, expected: int, label: str) -> None:
    if type(value) is not int or value != expected:
        raise ProductionWorkerError(f"{label} must be the exact integer {expected}")


def _safe_root(name: str) -> Path:
    value = os.environ.get(name)
    if not value or value != os.path.abspath(value):
        raise ProductionWorkerTrustError(f"{name} is not a lexical-canonical absolute root")
    candidate = Path(value)
    cursor = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        cursor /= part
        try:
            metadata = cursor.lstat()
        except OSError as error:
            raise ProductionWorkerTrustError(f"{name} ancestry is unavailable") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise ProductionWorkerTrustError(f"{name} ancestry contains a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ProductionWorkerTrustError(f"{name} is unavailable") from error
    if resolved != candidate or not candidate.is_dir():
        raise ProductionWorkerTrustError(f"{name} must be a directory")
    return candidate


def _contains(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validated_request(value: Any) -> dict[str, Any]:
    request = _exact(
        value,
        {
            "schema_version",
            "protocol",
            "authority_manifest_sha256",
            "source_bundle_manifest_sha256",
            "dependency_bundle_manifest_sha256",
            "capsule_manifest_sha256",
            "candidate_manifest_sha256",
            "semantic_registry_sha256",
            "run_nonce",
            "expected",
            "executions",
        },
        "worker request",
    )
    if type(request["schema_version"]) is not int or request["schema_version"] != 2:
        raise ProductionWorkerError("worker schema version is invalid")
    if request["protocol"] != PROTOCOL:
        raise ProductionWorkerError("worker protocol is invalid")
    for field in (
        "authority_manifest_sha256",
        "source_bundle_manifest_sha256",
        "dependency_bundle_manifest_sha256",
        "capsule_manifest_sha256",
        "candidate_manifest_sha256",
        "semantic_registry_sha256",
    ):
        if not isinstance(request[field], str) or HASH_PATTERN.fullmatch(request[field]) is None:
            raise ProductionWorkerError(f"worker {field} is invalid")
    if (
        not isinstance(request["run_nonce"], str)
        or re.fullmatch(r"[0-9a-f]{64}", request["run_nonce"]) is None
    ):
        raise ProductionWorkerError("worker run nonce is invalid")
    expected = _exact(request["expected"], {"candidates", "executions", "roles"}, "expected")
    _exact_int(expected["candidates"], 3, "worker expected candidate count")
    _exact_int(expected["executions"], 5, "worker expected execution count")
    roles = _exact(expected["roles"], set(ROLE_COUNTS), "worker expected roles")
    for role, count in ROLE_COUNTS.items():
        _exact_int(roles[role], count, f"worker expected {role} role count")
    rows = request["executions"]
    if not isinstance(rows, list) or len(rows) != 5:
        raise ProductionWorkerError("worker execution roster must contain exactly five rows")
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        row = _exact(
            row,
            {
                "candidate_id",
                "family",
                "role",
                "expected_status",
                "request",
                "capsule_envelope",
            },
            f"worker execution {index}",
        )
        identity = (row["candidate_id"], row["role"])
        if (
            not isinstance(row["candidate_id"], str)
            or ID_PATTERN.fullmatch(row["candidate_id"]) is None
            or row["role"] not in ROLE_FAMILY
            or row["family"] != ROLE_FAMILY[row["role"]]
            or row["expected_status"] not in {"ok", "invalid"}
            or not isinstance(row["request"], dict)
            or not isinstance(row["capsule_envelope"], dict)
            or identity in seen
        ):
            raise ProductionWorkerError("worker execution identity is invalid")
        if row["expected_status"] != ROLE_EXPECTED_STATUS[row["role"]]:
            raise ProductionWorkerError("worker execution status differs from its registered role")
        seen.add(identity)
    if Counter(role for _, role in seen) != Counter(ROLE_COUNTS):
        raise ProductionWorkerError("worker role roster is not exact")
    if len({candidate for candidate, _ in seen}) != 3:
        raise ProductionWorkerError("worker candidate denominator is not exact")
    return request


def _write_artifact(output_root: Path, relative: str, raw: bytes) -> Path:
    artifact = output_root / relative
    current = output_root
    for part in Path(relative).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ProductionWorkerTrustError("worker artifact path crosses a symlink")
        current.mkdir(mode=0o700, exist_ok=True)
    if artifact.exists() or artifact.is_symlink():
        raise ProductionWorkerTrustError("worker artifact target already exists")
    temporary = artifact.with_name(f".{artifact.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise ProductionWorkerTrustError("worker artifact temporary path already exists")
    try:
        temporary.write_bytes(raw)
        os.replace(temporary, artifact)
    except OSError as error:
        raise ProductionWorkerExecutionError("worker artifact could not be written") from error
    return artifact


def execute(value: Any) -> dict[str, Any]:
    request = _validated_request(value)
    process_root = _safe_root("W3_PRODUCTION_PROCESS_ROOT")
    output_root = _safe_root("W3_PRODUCTION_OUTPUT_ROOT")
    if not _contains(process_root, output_root):
        raise ProductionWorkerTrustError("worker output root must stay below process root")
    verified: list[dict[str, Any]] = []
    for row in sorted(request["executions"], key=lambda item: (item["candidate_id"], item["role"])):
        artifact_relative = f"artifacts/{row['candidate_id']}/{row['role']}.json"
        artifact = output_root / artifact_relative
        capsule_request = {
            "schema_version": 2,
            "protocol": "metis-runtime-capsule-v2",
            "execution_id": f"{row['candidate_id']}.{row['role']}",
            "run_nonce": request["run_nonce"],
            "capsule_manifest_sha256": request["capsule_manifest_sha256"],
            "request": row["request"],
        }
        envelope = row["capsule_envelope"]
        try:
            verify_capsule_oracle_envelope(envelope, capsule_request=capsule_request)
        except OracleError as error:
            raise ProductionWorkerTrustError(
                f"capsule evidence {row['candidate_id']}/{row['role']} failed verification"
            ) from error
        if envelope["oracle_envelope"]["result"]["status"] != row["expected_status"]:
            raise ProductionWorkerTrustError(
                "capsule result status differs from the registered role"
            )
        raw = _canonical(envelope)
        artifact = _write_artifact(output_root, artifact_relative, raw)
        if artifact.read_bytes() != raw:
            raise ProductionWorkerTrustError("capsule artifact bytes differ from its envelope")
        normalized = normalize_capsule_oracle_envelope(envelope)
        verified.append(
            {
                "candidate_id": row["candidate_id"],
                "family": row["family"],
                "role": row["role"],
                "expected_status": row["expected_status"],
                "request": row["request"],
                "request_sha256": _sha(row["request"]),
                "capsule_envelope": envelope,
                "capsule_envelope_sha256": _sha(normalized),
                "oracle_envelope_sha256": _sha(envelope["oracle_envelope"]),
                "result_sha256": _sha(envelope["oracle_envelope"]["result"]),
                "artifact_path": artifact_relative,
                "artifact_sha256": _bytes_sha(raw),
                "normalized_artifact_sha256": _bytes_sha(_canonical(normalized)),
            }
        )
    body = {
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL,
        "status": "completed",
        "authority_manifest_sha256": request["authority_manifest_sha256"],
        "run_nonce": request["run_nonce"],
        "counts": {"candidates": 3, "executions": 5, "distinct": 5, "gaps": 0},
        "roles": ROLE_COUNTS,
        "executions": verified,
    }
    return {**body, "manifest_sha256": _sha({k: v for k, v in body.items() if k != "run_nonce"})}


def _blocked(error: ProductionWorkerError) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL,
        "status": "blocked",
        "failure": {"kind": error.kind, "message": str(error)},
    }


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        result = _blocked(ProductionWorkerError("worker input exceeds its cap"))
        sys.stdout.buffer.write(_canonical(result))
        return 2
    try:
        value = json.loads(raw)
        if raw != _canonical(value):
            raise ProductionWorkerError("worker input is not canonical JSON")
        result = execute(value)
        rendered = _canonical(result)
        if len(rendered) > MAX_OUTPUT_BYTES:
            raise ProductionWorkerExecutionError("worker output exceeds its cap")
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        failure = ProductionWorkerError("worker input is not valid JSON")
        result = _blocked(failure)
        rendered = _canonical(result)
        del error
        code = 2
    except ProductionWorkerError as error:
        result = _blocked(error)
        rendered = _canonical(result)
        code = 2
    else:
        code = 0
    sys.stdout.buffer.write(rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
