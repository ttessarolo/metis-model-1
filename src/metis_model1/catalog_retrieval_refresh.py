"""Execute the pinned catalog retrieval CLI against a public fixture only.

This is a maintenance receipt path, not the production W3 Oracle.  It archives
the exact catalog implementation commit, copies the already-pinned runtime,
copies a hash-checked public fixture into that snapshot, and runs only
``catalog-domain.ts`` under the same cooperative local sandbox used by the pin
verifier.  The returned report contains hashes and redacted summaries only.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

import metis_model1.catalog_maintenance_pin as pin
from metis_model1.catalog_retrieval import (
    CatalogRetrievalError,
    adapt_catalog_retrieval_response,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "manifests/catalog-retrieval-public-synthetic-v1.json"
EXECUTION_RECEIPT_PATH = PROJECT_ROOT / "manifests/catalog-retrieval-execution-v1.json"
SCHEMA_PATH = PROJECT_ROOT / "schemas/catalog-retrieval-execution-receipt.schema.json"
FIXTURE_ROOT = PROJECT_ROOT / "fixtures/catalog-maintenance/public-synthetic-v1"
MANIFEST_SHA256 = "sha256:203ed68a1574c869910fc0b096cfa3a760a3e0b6857a9fb89d1902d582241bb2"
EXECUTION_RECEIPT_SHA256 = "sha256:dd5a2b3046842dba35bffd06111882caafe52c66d80bd1f0d3b7c3a7d911ea5b"
SCHEMA_SHA256 = "sha256:22d90adf2ad28eaaf81285dccbd29058311573c1e8dd71bac4fd3c2edf0e8046"
MAX_MANIFEST_BYTES = 512 * 1024
MAX_FIXTURE_FILES = 64
MAX_FIXTURE_BYTES = 4 * 1024 * 1024
MAX_STDOUT_BYTES = 16 * 1024 * 1024
MAX_STDERR_BYTES = 128 * 1024
NONCLAIMS = [
    "not_same_uid_adversary_resistant",
    "not_general_untrusted_code_sandbox",
    "no_external_execution_attestation",
    "no_model_output",
    "no_training_authority",
    "no_accuracy_claim",
    "nonpromotable",
]


class CatalogRetrievalRefreshError(ValueError):
    """Raised when the public-synthetic retrieval refresh fails closed."""


@dataclass(frozen=True)
class CatalogQuery:
    """One path-inert catalog-domain CLI query."""

    query_id: str
    operation: str
    catalog: str | None
    field: str | None
    expected: Mapping[str, Any]


@dataclass(frozen=True)
class _Execution:
    parsed: dict[str, Any]
    raw: bytes
    stderr_sha256: str


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CatalogRetrievalRefreshError(f"value is not canonical JSON: {error}") from error


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _safe_relative(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CatalogRetrievalRefreshError(f"{label} is not a safe relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(part == ".git" or part.startswith(".env") for part in path.parts)
    ):
        raise CatalogRetrievalRefreshError(f"{label} is not a safe relative POSIX path")
    return path


def _stable_bytes(path: Path, label: str, limit: int) -> bytes:
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_size > limit:
            raise CatalogRetrievalRefreshError(f"{label} is not a bounded regular file")
        raw = os.read(descriptor, opened.st_size + 1)
        after = os.fstat(descriptor)
        path_after = path.lstat()
    except OSError as error:
        raise CatalogRetrievalRefreshError(f"{label} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity = lambda value: (  # noqa: E731 - immutable stat identity
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
        or len(raw) != before.st_size
    ):
        raise CatalogRetrievalRefreshError(f"{label} changed while it was read")
    return raw


def _load_manifest(root: Path = PROJECT_ROOT) -> tuple[dict[str, Any], str]:
    path = root.resolve(strict=True) / MANIFEST_PATH.relative_to(PROJECT_ROOT)
    raw = _stable_bytes(path, "public-synthetic manifest", MAX_MANIFEST_BYTES)
    digest = _sha256(raw)
    if digest != MANIFEST_SHA256:
        raise CatalogRetrievalRefreshError(
            "public-synthetic manifest differs from its fixed digest"
        )
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogRetrievalRefreshError("public-synthetic manifest is not valid JSON") from error
    if not isinstance(manifest, dict):
        raise CatalogRetrievalRefreshError("public-synthetic manifest must be an object")
    return manifest, digest


def _fixture_records(
    fixture_root: Path,
    manifest: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    fixture = fixture_root.resolve(strict=True)
    if fixture.is_symlink() or not fixture.is_dir():
        raise CatalogRetrievalRefreshError("public-synthetic fixture root is not a directory")
    expected = manifest.get("files")
    if not isinstance(expected, list) or not expected or len(expected) > MAX_FIXTURE_FILES:
        raise CatalogRetrievalRefreshError("public-synthetic fixture file roster is invalid")
    records: list[dict[str, Any]] = []
    expected_paths: set[str] = set()
    total = 0
    for item in expected:
        if not isinstance(item, Mapping) or set(item) != {"path", "bytes", "sha256"}:
            raise CatalogRetrievalRefreshError("public-synthetic fixture manifest entry is invalid")
        relative = _safe_relative(item["path"], "fixture file path")
        path_text = relative.as_posix()
        if path_text in expected_paths:
            raise CatalogRetrievalRefreshError("public-synthetic fixture file paths are duplicated")
        expected_paths.add(path_text)
        path = fixture / Path(*relative.parts)
        raw = _stable_bytes(path, f"fixture file {path_text}", MAX_FIXTURE_BYTES)
        digest = _sha256(raw)
        if len(raw) != item["bytes"] or digest != item["sha256"]:
            raise CatalogRetrievalRefreshError(f"public-synthetic fixture file drift: {path_text}")
        total += len(raw)
        records.append({"path": path_text, "bytes": len(raw), "sha256": digest})
    actual_paths: set[str] = set()
    for path in fixture.rglob("*"):
        relative = path.relative_to(fixture)
        if path.is_symlink():
            raise CatalogRetrievalRefreshError("public-synthetic fixture contains a symlink")
        if path.is_file():
            actual_paths.add(relative.as_posix())
        elif not path.is_dir():
            raise CatalogRetrievalRefreshError("public-synthetic fixture contains a special file")
    if actual_paths != expected_paths:
        raise CatalogRetrievalRefreshError("public-synthetic fixture has an extra or missing file")
    if total > MAX_FIXTURE_BYTES:
        raise CatalogRetrievalRefreshError("public-synthetic fixture exceeds its byte cap")
    records.sort(key=lambda item: item["path"])
    fixture_hash = _sha256(
        _canonical(
            {
                "fixture_id": manifest["fixture_id"],
                "tenant_id": manifest["tenant_id"],
                "files": records,
            }
        )
    )
    return records, fixture_hash


def _copy_fixture(
    fixture_root: Path, destination: Path, records: Sequence[Mapping[str, Any]]
) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for record in records:
        relative = _safe_relative(record["path"], "fixture copy path")
        source = fixture_root / Path(*relative.parts)
        target = destination / Path(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = _stable_bytes(source, f"fixture file {relative}", MAX_FIXTURE_BYTES)
        if len(raw) != record["bytes"] or _sha256(raw) != record["sha256"]:
            raise CatalogRetrievalRefreshError(
                f"fixture file changed before copy: {relative.as_posix()}"
            )
        target.write_bytes(raw)


@dataclass
class _Snapshot:
    root: Path
    tooling: Path
    node: Path
    policy: str
    fixture: Path

    def run(self, query: CatalogQuery) -> _Execution:
        if query.operation not in {"describe", "values"}:
            raise CatalogRetrievalRefreshError("operation must be describe or values")
        command = [
            str(self.node),
            "--import",
            "tsx",
            "src/cli/catalog-domain.ts",
            query.operation,
            "--tenant",
            str(self.fixture),
        ]
        if query.catalog is not None:
            command.extend(("--catalog", query.catalog))
        if query.field is not None:
            command.extend(("--field", query.field))
        try:
            completed = subprocess.run(
                [str(pin.SANDBOX_EXEC), "-p", self.policy, *command],
                cwd=self.tooling,
                check=False,
                capture_output=True,
                timeout=pin.PROBE_TIMEOUT_SECONDS,
                env=pin._probe_process_environment(),
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise CatalogRetrievalRefreshError(
                "catalog retrieval process failed to start"
            ) from error
        if len(completed.stdout) > MAX_STDOUT_BYTES or len(completed.stderr) > MAX_STDERR_BYTES:
            raise CatalogRetrievalRefreshError("catalog retrieval output exceeds its byte cap")
        stderr_sha256 = _sha256(completed.stderr)
        if completed.returncode != 0 or not completed.stdout:
            raise CatalogRetrievalRefreshError(
                f"catalog query failed: returncode={completed.returncode} "
                f"stdout={_sha256(completed.stdout)} stderr={stderr_sha256}"
            )
        try:
            parsed, raw = pin_module_parse_response(completed.stdout)
        except CatalogRetrievalError as error:
            raise CatalogRetrievalRefreshError(
                f"catalog query output is invalid: {error}"
            ) from error
        return _Execution(parsed=parsed, raw=raw, stderr_sha256=stderr_sha256)


def pin_module_parse_response(value: bytes) -> tuple[dict[str, Any], bytes]:
    """Use the existing strict response parser without duplicating its rules."""

    import metis_model1.catalog_retrieval as retrieval

    return retrieval._parse_response(value)


@contextmanager
def _pinned_snapshot(metis_root: Path, node_path: Path) -> Any:
    manifest = pin.load_catalog_maintenance_pin()
    metis = metis_root.resolve(strict=True)
    if not metis.is_dir():
        raise CatalogRetrievalRefreshError("Metis root must be a directory")
    try:
        archive = pin._run_git(
            metis,
            "archive",
            "--format=tar",
            manifest["revision"],
            "tooling",
            text=False,
        )
        assert isinstance(archive, bytes)
        node_bytes = pin._verify_node(node_path, manifest["runtime"])
        with tempfile.TemporaryDirectory(prefix="metis-model1-catalog-refresh-") as temporary:
            snapshot_root = Path(temporary)
            pin._safe_extract_archive(archive, snapshot_root)
            tooling = snapshot_root / "tooling"
            source_modules = (metis / "tooling/node_modules").resolve(strict=True)
            snapshot_modules = tooling / "node_modules"
            shutil.copytree(source_modules, snapshot_modules, symlinks=True)
            modules_sha256 = "sha256:" + pin._node_modules_sha256(snapshot_modules)
            if modules_sha256 != manifest["runtime"]["node_modules_sha256"]:
                raise CatalogRetrievalRefreshError("copied tooling node_modules differs from pin")
            node = snapshot_root / "pinned-node"
            node.write_bytes(node_bytes)
            node.chmod(0o500)
            policy = pin._sandbox_policy(snapshot_root)
            pin._assert_sandbox_boundaries(snapshot_root, policy)
            fixture = snapshot_root / "public-synthetic-tenant"
            yield _Snapshot(snapshot_root, tooling, node, policy, fixture)
    except CatalogRetrievalRefreshError:
        raise
    except (OSError, tarfile.TarError, subprocess.SubprocessError) as error:
        raise CatalogRetrievalRefreshError(
            "cannot construct the pinned catalog snapshot"
        ) from error


def _query_from_manifest(value: Any) -> CatalogQuery:
    if not isinstance(value, Mapping) or set(value) != {
        "id",
        "operation",
        "catalog",
        "field",
        "expected",
    }:
        raise CatalogRetrievalRefreshError("catalog query roster entry is invalid")
    query_id = value["id"]
    if not isinstance(query_id, str) or not query_id:
        raise CatalogRetrievalRefreshError("catalog query id is invalid")
    operation, catalog, field = pin_module_query(
        value["operation"], value["catalog"], value["field"]
    )
    expected = value["expected"]
    if not isinstance(expected, Mapping) or set(expected) != {
        "response_sha256",
        "output_sha256",
        "output_bytes",
        "receipt_sha256",
        "summary",
    }:
        raise CatalogRetrievalRefreshError("catalog query expected result is invalid")
    return CatalogQuery(query_id, operation, catalog, field, dict(expected))


def _expected_query_result(query: CatalogQuery) -> dict[str, Any]:
    return {
        "id": query.query_id,
        "query": {
            "operation": query.operation,
            "catalog": query.catalog,
            "field": query.field,
        },
        "status": "pass",
        **dict(query.expected),
    }


def pin_module_query(
    operation: Any, catalog: Any, field: Any
) -> tuple[str, str | None, str | None]:
    """Reuse the existing path-inert query validator."""

    import metis_model1.catalog_retrieval as retrieval

    try:
        return retrieval._query(operation, catalog, field)
    except CatalogRetrievalError as error:
        raise CatalogRetrievalRefreshError(str(error)) from error


def _report_hash(value: Mapping[str, Any]) -> str:
    return _sha256(
        _canonical({key: item for key, item in value.items() if key != "receipt_sha256"})
    )


def _no_values(value: Any) -> None:
    if isinstance(value, Mapping):
        if "values" in value:
            raise CatalogRetrievalRefreshError("execution report must never contain catalog values")
        for item in value.values():
            _no_values(item)
    elif isinstance(value, list):
        for item in value:
            _no_values(item)


def validate_catalog_retrieval_refresh_contract(
    root: Path = PROJECT_ROOT,
) -> list[str]:
    """Validate the pinned fixture and golden roster without claiming execution."""

    try:
        manifest, manifest_sha256 = _load_manifest(root)
        if set(manifest) != {
            "schema_version",
            "fixture_id",
            "fixture_root",
            "tenant_id",
            "files",
            "queries",
            "policy",
        }:
            raise CatalogRetrievalRefreshError("public-synthetic manifest fields drifted")
        if (
            manifest["schema_version"] != 1
            or manifest["fixture_id"] != "catalog-retrieval/public-synthetic-v1"
            or manifest["tenant_id"] != "model1-public-synthetic"
            or manifest["policy"]
            != {
                "public_synthetic_only": True,
                "no_live_tenant": True,
                "no_values_in_receipts": True,
            }
        ):
            raise CatalogRetrievalRefreshError("public-synthetic manifest identity drifted")
        fixture_relative = _safe_relative(manifest["fixture_root"], "fixture root")
        if fixture_relative.as_posix() != FIXTURE_ROOT.relative_to(PROJECT_ROOT).as_posix():
            raise CatalogRetrievalRefreshError("public-synthetic fixture root drifted")
        records, _fixture_hash = _fixture_records(
            root.resolve(strict=True) / Path(*fixture_relative.parts), manifest
        )
        queries = [_query_from_manifest(item) for item in manifest["queries"]]
        if not queries or len({query.query_id for query in queries}) != len(queries):
            raise CatalogRetrievalRefreshError("public-synthetic query roster is not distinct")
        pin_errors = pin.validate_catalog_maintenance_pin_contract(root)
        if pin_errors:
            raise CatalogRetrievalRefreshError(
                "catalog maintenance pin is invalid: " + "; ".join(pin_errors)
            )
        pin_manifest = pin.load_catalog_maintenance_pin(root)
        report: dict[str, Any] = {
            "schema_version": 1,
            "status": "verified_local_cooperative",
            "authority_scope": "public_synthetic_archive_snapshot_only",
            "fixture": {
                "id": manifest["fixture_id"],
                "tenant_id": manifest["tenant_id"],
                "manifest_sha256": manifest_sha256,
                "files": records,
            },
            "upstream": {
                "pin_id": pin_manifest["pin_id"],
                "revision": pin_manifest["revision"],
                "tree": pin_manifest["tree"],
                "manifest_sha256": pin.manifest_sha256(pin_manifest),
                "verification": "archive_snapshot",
            },
            "execution": {
                "command": "catalog-domain.ts",
                "sandbox": "deny-write-deny-network",
                "values_redacted": True,
            },
            "queries": [_expected_query_result(query) for query in queries],
            "counts": {
                "queries_in": len(queries),
                "queries_out": len(queries),
                "queries_distinct": len(queries),
                "queries_gaps": 0,
            },
            "policy": {
                "archive_execution": True,
                "network_denied": True,
                "writes_denied": True,
                "public_synthetic_only": True,
                "golden_outputs_pinned": True,
                "model_output_observed": False,
                "training_authorized": False,
            },
            "nonclaims": list(NONCLAIMS),
        }
        _no_values(report)
        report["receipt_sha256"] = _report_hash(report)
        errors = validate_catalog_retrieval_refresh_report(report, root=root)
        if errors:
            return errors
        receipt_errors = validate_catalog_retrieval_execution_evidence(root)
        if receipt_errors:
            return receipt_errors
        tracked = _load_execution_receipt(root)
        if tracked != report:
            return ["tracked execution receipt differs from the exact golden contract"]
        return []
    except (
        OSError,
        CatalogRetrievalRefreshError,
        pin.CatalogMaintenancePinError,
    ) as error:
        return [f"catalog retrieval refresh contract failed closed: {error}"]


def _load_execution_receipt(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    receipt_path = root.resolve(strict=True) / EXECUTION_RECEIPT_PATH.relative_to(PROJECT_ROOT)
    raw = _stable_bytes(receipt_path, "catalog retrieval execution receipt", MAX_MANIFEST_BYTES)
    if _sha256(raw) != EXECUTION_RECEIPT_SHA256:
        raise CatalogRetrievalRefreshError(
            "catalog retrieval execution receipt differs from its fixed digest"
        )
    try:
        receipt = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogRetrievalRefreshError(
            "catalog retrieval execution receipt is not valid JSON"
        ) from error
    if not isinstance(receipt, dict):
        raise CatalogRetrievalRefreshError("catalog retrieval execution receipt must be an object")
    return receipt


def validate_catalog_retrieval_execution_evidence(
    root: Path = PROJECT_ROOT,
) -> list[str]:
    """Validate the tracked redacted receipt; this is not external attestation."""

    try:
        receipt = _load_execution_receipt(root)
        return validate_catalog_retrieval_refresh_report(receipt, root=root)
    except (OSError, CatalogRetrievalRefreshError) as error:
        return [f"catalog retrieval execution evidence failed closed: {error}"]


def run_catalog_retrieval_refresh(
    metis_root: Path,
    node_path: Path,
    *,
    fixture_root: Path = FIXTURE_ROOT,
    root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    """Run the fixed public-synthetic retrieval roster in one pinned snapshot."""

    manifest, manifest_sha256 = _load_manifest(root)
    if manifest.get("policy") != {
        "public_synthetic_only": True,
        "no_live_tenant": True,
        "no_values_in_receipts": True,
    }:
        raise CatalogRetrievalRefreshError("public-synthetic fixture policy drift")
    contract_errors = pin.validate_catalog_maintenance_pin_contract(root)
    if contract_errors:
        raise CatalogRetrievalRefreshError(
            "catalog maintenance pin is invalid: " + "; ".join(contract_errors)
        )
    try:
        pin_report = pin.verify_catalog_maintenance_pin(metis_root, node_path)
    except pin.CatalogMaintenancePinError as error:
        raise CatalogRetrievalRefreshError(
            f"catalog implementation pin verification stopped: {error}"
        ) from error
    if pin_report["status"] != "verified_local_cooperative":
        raise CatalogRetrievalRefreshError("catalog implementation pin is not locally verified")
    records, fixture_sha256 = _fixture_records(fixture_root, manifest)
    fixture = fixture_root.resolve(strict=True)
    queries = [_query_from_manifest(item) for item in manifest["queries"]]
    if len({query.query_id for query in queries}) != len(queries):
        raise CatalogRetrievalRefreshError("catalog query IDs are duplicated")
    tenant_input_sha256 = fixture_sha256
    results: list[dict[str, Any]] = []
    with _pinned_snapshot(metis_root, node_path) as snapshot:
        _copy_fixture(fixture, snapshot.fixture, records)
        copied_records, copied_fixture_sha256 = _fixture_records(snapshot.fixture, manifest)
        if copied_records != records or copied_fixture_sha256 != fixture_sha256:
            raise CatalogRetrievalRefreshError("copied public-synthetic fixture differs from pin")
        for query in queries:
            execution = snapshot.run(query)
            try:
                receipt = adapt_catalog_retrieval_response(
                    query.operation,
                    execution.raw,
                    tenant_input_sha256=tenant_input_sha256,
                    catalog=query.catalog,
                    field=query.field,
                    root=root,
                )
            except CatalogRetrievalError as error:
                raise CatalogRetrievalRefreshError(
                    f"retrieval receipt failed: {query.query_id}: {error}"
                ) from error
            result = {
                "id": query.query_id,
                "query": {
                    "operation": query.operation,
                    "catalog": query.catalog,
                    "field": query.field,
                },
                "status": "pass",
                "response_sha256": receipt["hashes"]["response_sha256"],
                "output_sha256": receipt["hashes"]["output_sha256"],
                "output_bytes": receipt["hashes"]["output_bytes"],
                "receipt_sha256": receipt["receipt_sha256"],
                "summary": receipt["summary"],
            }
            if result != _expected_query_result(query):
                raise CatalogRetrievalRefreshError(
                    f"catalog query differs from pinned golden: {query.query_id}"
                )
            results.append(result)
        final_records, final_fixture_sha256 = _fixture_records(snapshot.fixture, manifest)
        if final_records != records or final_fixture_sha256 != fixture_sha256:
            raise CatalogRetrievalRefreshError("public-synthetic fixture changed during execution")
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "verified_local_cooperative",
        "authority_scope": "public_synthetic_archive_snapshot_only",
        "fixture": {
            "id": manifest["fixture_id"],
            "tenant_id": manifest["tenant_id"],
            "manifest_sha256": manifest_sha256,
            "files": records,
        },
        "upstream": {
            "pin_id": pin_report["pin_id"],
            "revision": pin_report["revision"],
            "tree": pin_report["tree"],
            "manifest_sha256": pin_report["manifest_sha256"],
            "verification": "archive_snapshot",
        },
        "execution": {
            "command": "catalog-domain.ts",
            "sandbox": "deny-write-deny-network",
            "values_redacted": True,
        },
        "queries": results,
        "counts": {
            "queries_in": len(queries),
            "queries_out": len(results),
            "queries_distinct": len({item["id"] for item in results}),
            "queries_gaps": len(queries) - len(results),
        },
        "policy": {
            "archive_execution": True,
            "network_denied": True,
            "writes_denied": True,
            "public_synthetic_only": True,
            "golden_outputs_pinned": True,
            "model_output_observed": False,
            "training_authorized": False,
        },
        "nonclaims": list(NONCLAIMS),
    }
    _no_values(report)
    report["receipt_sha256"] = _report_hash(report)
    errors = validate_catalog_retrieval_refresh_report(report, root=root)
    if errors:
        raise CatalogRetrievalRefreshError(
            "generated execution receipt is invalid: " + "; ".join(errors)
        )
    return report


def validate_catalog_retrieval_refresh_report(
    report: Any,
    *,
    root: Path = PROJECT_ROOT,
) -> list[str]:
    """Validate schema, hash binding, exact pin and redaction invariants."""

    try:
        schema_raw = _stable_bytes(
            root.resolve(strict=True) / SCHEMA_PATH.relative_to(PROJECT_ROOT),
            "catalog retrieval execution schema",
            MAX_MANIFEST_BYTES,
        )
        if _sha256(schema_raw) != SCHEMA_SHA256:
            return ["catalog retrieval execution schema differs from its fixed digest"]
        schema = json.loads(schema_raw.decode("utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(report),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
        if errors:
            return [
                (
                    f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: "
                    f"{error.message}"
                )
                for error in errors
            ]
        if not isinstance(report, Mapping):
            return ["report must be an object"]
        _no_values(report)
        if report["receipt_sha256"] != _report_hash(report):
            return ["receipt_sha256 does not match the canonical report"]
        manifest, digest = _load_manifest(root)
        if report["fixture"] != {
            "id": manifest["fixture_id"],
            "tenant_id": manifest["tenant_id"],
            "manifest_sha256": digest,
            "files": report["fixture"]["files"],
        }:
            return ["fixture manifest hash drift"]
        fixture_relative = _safe_relative(manifest["fixture_root"], "fixture root")
        expected_fixture_relative = FIXTURE_ROOT.relative_to(PROJECT_ROOT).as_posix()
        if fixture_relative.as_posix() != expected_fixture_relative:
            return ["fixture root differs from the fixed public-synthetic root"]
        records, _fixture_hash = _fixture_records(
            root.resolve(strict=True) / Path(*fixture_relative.parts), manifest
        )
        expected_files = report["fixture"]["files"]
        if expected_files != records:
            return ["fixture file roster or hash drift"]
        pin_errors = pin.validate_catalog_maintenance_pin_contract(root)
        if pin_errors:
            return ["catalog maintenance pin is invalid: " + "; ".join(pin_errors)]
        pin_manifest = pin.load_catalog_maintenance_pin(root)
        expected_upstream = {
            "pin_id": pin_manifest["pin_id"],
            "revision": pin_manifest["revision"],
            "tree": pin_manifest["tree"],
            "manifest_sha256": pin.manifest_sha256(pin_manifest),
            "verification": "archive_snapshot",
        }
        if report["upstream"] != expected_upstream:
            return ["upstream identity differs from the exact catalog pin"]
        queries = [_query_from_manifest(item) for item in manifest["queries"]]
        expected_queries = [_expected_query_result(query) for query in queries]
        if report["queries"] != expected_queries:
            return ["query roster or pinned result drift"]
        expected_counts = {
            "queries_in": len(queries),
            "queries_out": len(queries),
            "queries_distinct": len({query.query_id for query in queries}),
            "queries_gaps": 0,
        }
        if expected_counts["queries_distinct"] != len(queries):
            return ["manifest query roster is not distinct"]
        if report["counts"] != expected_counts:
            return ["query coverage or distinctness drift"]
        if report["nonclaims"] != NONCLAIMS:
            return ["execution report nonclaims drift"]
        return []
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        CatalogRetrievalRefreshError,
    ) as error:
        return [f"report validation failed closed: {error}"]
