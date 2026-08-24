"""Fail-closed F-5 public-synthetic migration oracle.

This module deliberately runs the Metis migrator only with an explicitly
provided synthetic legacy tree and synthetic golden workspace.  It never uses
the migrator defaults, which point at a private legacy tenant.  A successful
process is insufficient: the local runner reports green only when one migration
is recompiled cleanly, has exact canonical-IR parity with its independently
authored golden, and carries no ``NON_PROMOTE`` marker.  The result is always a
non-promotional local observation; it is not a protected execution receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from . import oracles as metis_oracles

PINNED_METIS_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
PINNED_METIS_TREE = "75473e26deff4084a0eb077a4c3e27d52dc07998"
PINNED_MIGRATOR_SHA256 = "564217eddf0aa417b39fa6eb11302469fbf5c2cd4e10b221716a40b27418373b"
PINNED_MIGRATION_CHECK_SHA256 = "6e93340b949df8b0e42cdee92b338d5cd19ca82cf34e74f0b089356f8f41bfa5"
FAMILY = "F-5"
SCHEMA_VERSION = 1

_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^f5/public-synthetic/[a-z0-9][a-z0-9._-]{0,80}$")
_ENDPOINT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ENDPOINT_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_ENDPOINT_DECL_RE = re.compile(
    r"(?m)^[ \t]*endpoint[ \t]+([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)[ \t]*\{"
)
_NONCE_RE = re.compile(r"^[0-9a-f]{64}$")
_MIGRATED_RE = re.compile(r"(?m)^- `check` — ricompilati senza errori:\s*(\d+)/(\d+)")
_PARITY_RE = re.compile(r"(?m)^- `check` — .*parity golden:\s*(\d+) ok\s*/\s*(\d+) diverge")
_FAILURE_REASONS = frozenset(
    {
        "fixture_invalid",
        "source_hash_mismatch",
        "golden_hash_mismatch",
        "golden_not_043",
        "golden_endpoint_mismatch",
        "runner_error",
        "runner_timeout",
        "toolchain_mismatch",
        "checkout_changed",
        "base_hash_mismatch",
        "output_not_fresh",
        "output_roster_mismatch",
        "migrated_source_mismatch",
        "process_failed",
        "migrated_not_1_of_1",
        "diagnostics_present",
        "parity_not_1_ok_0_diverge",
        "missing_ir_parity_ok",
        "non_promote_present",
    }
)


class F5MigrationError(ValueError):
    """Base error for the F-5 migration boundary."""


class F5FixtureError(F5MigrationError):
    """Raised when a public-synthetic migration fixture is not sealed."""


class F5ResultError(F5MigrationError):
    """Raised when a migration result is malformed or self-inconsistent."""


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise F5MigrationError("value is not canonical JSON") from error


def _sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _bytes_sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise F5MigrationError("pinned toolchain file is missing or not regular")
    return _bytes_sha(path.read_bytes())


def _git_full_status(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise F5MigrationError("cannot inspect pinned Metis checkout") from error
    return completed.stdout


def _registered_execution_identity() -> dict[str, str]:
    return {
        "revision": PINNED_METIS_REVISION,
        "tree": PINNED_METIS_TREE,
        "node_version": metis_oracles.PINNED_NODE_VERSION,
        "node_binary_sha256": "sha256:" + metis_oracles.PINNED_NODE_BINARY_SHA256,
        "tooling_package_sha256": "sha256:" + metis_oracles.PINNED_TOOLING_PACKAGE_SHA256,
        "tooling_lock_sha256": "sha256:" + metis_oracles.PINNED_TOOLING_LOCK_SHA256,
        "node_modules_sha256": "sha256:" + metis_oracles.PINNED_NODE_MODULES_SHA256,
        "migrator_sha256": "sha256:" + PINNED_MIGRATOR_SHA256,
        "migration_check_sha256": "sha256:" + PINNED_MIGRATION_CHECK_SHA256,
    }


def _pinned_execution_identity(metis_root: Path) -> tuple[Path, Path, dict[str, str]]:
    try:
        root, revision, tree, tooling = metis_oracles.validate_pinned_metis(metis_root)
        node, node_sha256 = metis_oracles._resolve_pinned_node()
    except metis_oracles.OracleError as error:
        raise F5MigrationError("F-5 toolchain differs from the pinned Metis runtime") from error
    cli = root / "tooling/src/migrate/cli.ts"
    check = root / "tooling/src/migrate/check.ts"
    if _file_sha(cli) != "sha256:" + PINNED_MIGRATOR_SHA256:
        raise F5MigrationError("F-5 migrator bytes differ from the pin")
    if _file_sha(check) != "sha256:" + PINNED_MIGRATION_CHECK_SHA256:
        raise F5MigrationError("F-5 migration checker bytes differ from the pin")
    identity = {
        "revision": revision,
        "tree": tree,
        "node_version": metis_oracles.PINNED_NODE_VERSION,
        "node_binary_sha256": "sha256:" + node_sha256,
        "tooling_package_sha256": "sha256:" + tooling["package_sha256"],
        "tooling_lock_sha256": "sha256:" + tooling["lock_sha256"],
        "node_modules_sha256": "sha256:" + tooling["node_modules_sha256"],
        "migrator_sha256": "sha256:" + PINNED_MIGRATOR_SHA256,
        "migration_check_sha256": "sha256:" + PINNED_MIGRATION_CHECK_SHA256,
    }
    if identity != _registered_execution_identity():
        raise F5MigrationError("F-5 runtime identity differs from the registered pin")
    return root, node, identity


def _exact_mapping(value: Any, keys: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise F5MigrationError(f"{label} must contain exactly {sorted(keys)}")
    return value


def _safe_relative(path: str, *, suffix: str | None = None) -> str:
    if type(path) is not str or not path:
        raise F5MigrationError("path must be a non-empty relative string")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or parsed.name in {"", "."}:
        raise F5MigrationError("path must be a safe relative path")
    if suffix is not None and parsed.suffix != suffix:
        raise F5MigrationError(f"path must end in {suffix}")
    return path


def _require_hash(value: Any, label: str) -> str:
    if type(value) is not str or _HASH_RE.fullmatch(value) is None:
        raise F5MigrationError(f"{label} must be sha256:<64 hex>")
    return value


def _contained(root: Path, candidate: Path, label: str) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise F5MigrationError(f"{label} must stay inside the synthetic workspace") from error
    return resolved


def _tree_sha256(root: Path, allowed_suffixes: frozenset[str]) -> str:
    if not root.is_dir() or root.is_symlink():
        raise F5MigrationError("synthetic source root must be a real directory")
    rows: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise F5MigrationError("synthetic source tree contains a non-regular file")
        relative = path.relative_to(root).as_posix()
        if path.suffix not in allowed_suffixes or path.name.startswith(".env"):
            raise F5MigrationError("synthetic source tree contains a forbidden file type")
        rows.append((relative, _bytes_sha(path.read_bytes())))
    if not rows:
        raise F5MigrationError("synthetic source tree must contain at least one allowed file")
    return _sha(rows)


def _declared_golden_endpoints(raw: bytes) -> list[str]:
    try:
        return _ENDPOINT_DECL_RE.findall(raw.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise F5MigrationError("F-5 golden source must be UTF-8") from error


def _inspect_output_tree(output_root: Path, *, golden_path: str) -> tuple[Path, Path, str]:
    """Recompute the exact local output roster; reject every extra entry."""

    if not output_root.is_dir() or output_root.is_symlink():
        raise F5MigrationError("F-5 output root is missing, non-directory, or a symlink")
    expected_source = output_root / golden_path
    expected_report = output_root / "migrate-report.md"
    expected_dirs: set[Path] = set()
    parent = expected_source.parent
    while parent != output_root:
        expected_dirs.add(parent)
        parent = parent.parent
    expected_entries = expected_dirs | {expected_source, expected_report}
    entries = set(output_root.rglob("*"))
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in entries):
        raise F5MigrationError("F-5 output contains a symlink or non-regular entry")
    if entries != expected_entries:
        raise F5MigrationError("F-5 output roster differs from the exact expected tree")
    rows: list[tuple[str, str, str | None]] = []
    for path in sorted(entries):
        relative = path.relative_to(output_root).as_posix()
        if path.is_dir():
            rows.append(("dir", relative, None))
        else:
            rows.append(("file", relative, _file_sha(path)))
    return expected_source, expected_report, _sha(rows)


def _load_schema(name: str) -> dict[str, Any]:
    path = _repository_root() / "schemas" / name
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(value)
    except (OSError, json.JSONDecodeError, SchemaError) as error:
        raise F5MigrationError(f"F-5 schema {name} is unreadable") from error
    return value


def _schema_errors(value: Any, schema_name: str) -> list[str]:
    return sorted(
        error.message
        for error in Draft202012Validator(_load_schema(schema_name)).iter_errors(value)
    )


def seal_f5_fixture(
    *,
    fixture_id: str,
    endpoint_id: str,
    expected_endpoint: str,
    workspace_root: Path,
    legacy_root: Path,
    base_root: Path,
    golden_path: str,
) -> dict[str, Any]:
    """Seal a generic legacy tree and independently-authored current golden.

    The roots must live inside one caller-owned synthetic workspace.  They are
    intentionally not serialized into the portable fixture: only their
    content hashes and safe relative golden path are retained.
    """

    if _ID_RE.fullmatch(fixture_id) is None:
        raise F5FixtureError("F-5 fixture id is invalid")
    if type(endpoint_id) is not str or not endpoint_id or len(endpoint_id) > 128:
        raise F5FixtureError("F-5 endpoint id is invalid")
    if _ENDPOINT_ID_RE.fullmatch(endpoint_id) is None:
        raise F5FixtureError("F-5 endpoint id must be safe for the strict single-endpoint command")
    if _ENDPOINT_RE.fullmatch(expected_endpoint) is None:
        raise F5FixtureError("F-5 expected endpoint is invalid")
    golden_relative = _safe_relative(golden_path, suffix=".metis")
    property_name, endpoint_name = expected_endpoint.split(".", 1)
    if golden_relative != f"properties/{property_name}/{endpoint_name}.metis":
        raise F5FixtureError("F-5 golden path does not match the expected endpoint")
    workspace = workspace_root.resolve()
    legacy = _contained(workspace, legacy_root, "legacy root")
    base = _contained(workspace, base_root, "base root")
    golden = _contained(base, base / golden_relative, "golden path")
    if not golden.is_file() or golden.is_symlink():
        raise F5FixtureError("F-5 golden source is missing or not regular")
    golden_bytes = golden.read_bytes()
    if not golden_bytes.startswith(b"metis 0.43\n"):
        raise F5FixtureError("F-5 golden source must use metis 0.43")
    try:
        declared_endpoints = _declared_golden_endpoints(golden_bytes)
    except F5MigrationError as error:
        raise F5FixtureError(str(error)) from error
    if declared_endpoints != [expected_endpoint]:
        raise F5FixtureError("F-5 golden source must declare exactly the expected endpoint")
    body = {
        "schema_version": SCHEMA_VERSION,
        "fixture_id": fixture_id,
        "family": FAMILY,
        "classification": "public_synthetic",
        "model_outputs_observed": False,
        "toolchain": {
            "revision": PINNED_METIS_REVISION,
            "tree": PINNED_METIS_TREE,
            "language_version": "0.43",
            "migrator_path": "tooling/src/migrate/cli.ts",
            "migrator_sha256": "sha256:" + PINNED_MIGRATOR_SHA256,
            "migration_check_sha256": "sha256:" + PINNED_MIGRATION_CHECK_SHA256,
        },
        "legacy_source": {
            "tree_sha256": _tree_sha256(legacy, frozenset({".json"})),
            "endpoint_id": endpoint_id,
        },
        "base_source": {"tree_sha256": _tree_sha256(base, frozenset({".metis", ".json", ".toml"}))},
        "golden": {
            "path": golden_relative,
            "sha256": _bytes_sha(golden_bytes),
            "expected_endpoint": expected_endpoint,
        },
    }
    return {**body, "fixture_sha256": _sha(body)}


def validate_f5_fixture(value: Any) -> dict[str, Any]:
    """Validate and normalize a sealed public-synthetic F-5 fixture."""

    try:
        raw = _exact_mapping(
            value,
            frozenset(
                {
                    "schema_version",
                    "fixture_id",
                    "family",
                    "classification",
                    "model_outputs_observed",
                    "toolchain",
                    "legacy_source",
                    "base_source",
                    "golden",
                    "fixture_sha256",
                }
            ),
            "F-5 fixture",
        )
        if _schema_errors(raw, "f5-migration-fixture.schema.json"):
            raise F5FixtureError("F-5 fixture does not satisfy its schema")
        if (
            raw["schema_version"] != SCHEMA_VERSION
            or raw["family"] != FAMILY
            or raw["classification"] != "public_synthetic"
            or raw["model_outputs_observed"] is not False
            or _ID_RE.fullmatch(raw["fixture_id"]) is None
        ):
            raise F5FixtureError("F-5 fixture identity or authority is invalid")
        toolchain = _exact_mapping(
            raw["toolchain"],
            frozenset(
                {
                    "revision",
                    "tree",
                    "language_version",
                    "migrator_path",
                    "migrator_sha256",
                    "migration_check_sha256",
                }
            ),
            "F-5 toolchain",
        )
        if toolchain != {
            "revision": PINNED_METIS_REVISION,
            "tree": PINNED_METIS_TREE,
            "language_version": "0.43",
            "migrator_path": "tooling/src/migrate/cli.ts",
            "migrator_sha256": "sha256:" + PINNED_MIGRATOR_SHA256,
            "migration_check_sha256": "sha256:" + PINNED_MIGRATION_CHECK_SHA256,
        }:
            raise F5FixtureError("F-5 fixture toolchain pin differs from the ratified migrator")
        legacy = _exact_mapping(
            raw["legacy_source"], frozenset({"tree_sha256", "endpoint_id"}), "F-5 legacy"
        )
        tree_sha256 = _require_hash(legacy["tree_sha256"], "F-5 legacy tree hash")
        endpoint_id = legacy["endpoint_id"]
        if type(endpoint_id) is not str or _ENDPOINT_ID_RE.fullmatch(endpoint_id) is None:
            raise F5FixtureError("F-5 legacy endpoint id is invalid")
        base = _exact_mapping(raw["base_source"], frozenset({"tree_sha256"}), "F-5 base source")
        base_tree_sha256 = _require_hash(base["tree_sha256"], "F-5 base tree hash")
        golden = _exact_mapping(
            raw["golden"],
            frozenset({"path", "sha256", "expected_endpoint"}),
            "F-5 golden",
        )
        golden_path = _safe_relative(golden["path"], suffix=".metis")
        golden_sha256 = _require_hash(golden["sha256"], "F-5 golden hash")
        expected_endpoint = golden["expected_endpoint"]
        if _ENDPOINT_RE.fullmatch(expected_endpoint) is None:
            raise F5FixtureError("F-5 golden endpoint is invalid")
        property_name, endpoint_name = expected_endpoint.split(".", 1)
        if golden_path != f"properties/{property_name}/{endpoint_name}.metis":
            raise F5FixtureError("F-5 golden path does not match the expected endpoint")
        body = {
            "schema_version": SCHEMA_VERSION,
            "fixture_id": raw["fixture_id"],
            "family": FAMILY,
            "classification": "public_synthetic",
            "model_outputs_observed": False,
            "toolchain": dict(toolchain),
            "legacy_source": {"tree_sha256": tree_sha256, "endpoint_id": endpoint_id},
            "base_source": {"tree_sha256": base_tree_sha256},
            "golden": {
                "path": golden_path,
                "sha256": golden_sha256,
                "expected_endpoint": expected_endpoint,
            },
        }
        if raw["fixture_sha256"] != _sha(body):
            raise F5FixtureError("F-5 fixture hash does not match its canonical body")
        return {**body, "fixture_sha256": raw["fixture_sha256"]}
    except F5FixtureError:
        raise
    except F5MigrationError as error:
        raise F5FixtureError(str(error)) from error
    except Exception as error:  # noqa: BLE001 - untrusted fixture boundary
        raise F5FixtureError("F-5 fixture is malformed") from error


def _observed(
    stdout: str,
    stderr: str,
    returncode: int | None,
    *,
    expected_endpoint: str,
) -> dict[str, Any]:
    transcript = f"{stdout}\n{stderr}"
    # The upstream CLI prints this zero/zero *summary* on a clean run. It is
    # metadata, not a NON_PROMOTE finding; every other occurrence blocks F-5.
    transcript_without_clean_non_promote_summary = re.sub(
        r"NON_PROMOTE shape:\s*0 match\s*/\s*0 diverge",
        "",
        transcript,
    )
    migrated = _MIGRATED_RE.findall(transcript)
    parity = _PARITY_RE.findall(transcript)
    expected_name = expected_endpoint.split(".", 1)[1]
    expected_ir_marker = f"IR-PARITY OK ({expected_name})"
    return {
        "process_exit_code": returncode,
        "report_summary_count": len(migrated),
        "migrated_recompiled": int(migrated[0][0]) if len(migrated) == 1 else 0,
        "migrated_total": int(migrated[0][1]) if len(migrated) == 1 else 0,
        "parity_ok": int(parity[0][0]) if len(parity) == 1 else 0,
        "parity_diverge": int(parity[0][1]) if len(parity) == 1 else 0,
        "ir_parity_ok_count": transcript.count(expected_ir_marker),
        "diagnostics_seen": any(
            marker in transcript
            for marker in (
                "## Errori",
                "## Buchi di spec",
                "## Warning",
                "RICOMPILAZIONE:",
                "parser error",
                "validation error",
                "corpus-curato",
            )
        ),
        "non_promote_seen": "NON_PROMOTE" in transcript_without_clean_non_promote_summary,
        "stdout_sha256": _bytes_sha(stdout.encode("utf-8")),
        "stderr_sha256": _bytes_sha(stderr.encode("utf-8")),
    }


def _result(
    fixture: Mapping[str, Any],
    observed: Mapping[str, Any],
    reasons: Sequence[str],
    command: Sequence[str],
    *,
    run_nonce: str,
    execution_identity: Mapping[str, str] | None = None,
    artifacts: Mapping[str, Any] | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    normalized_reasons = sorted(set(reasons))
    if any(reason not in _FAILURE_REASONS for reason in normalized_reasons):
        raise F5MigrationError("F-5 result contains an unknown failure reason")
    runner_checks_passed = not normalized_reasons
    body = {
        "schema_version": SCHEMA_VERSION,
        "fixture_id": fixture["fixture_id"],
        "family": FAMILY,
        "run_nonce": run_nonce,
        "status": "runner_checks_passed" if runner_checks_passed else "blocked",
        "runner_checks_passed": runner_checks_passed,
        "evidence_class": "local_runner_observation",
        "promotion_eligible": False,
        "authority_gap": "protected_execution_receipt_missing",
        "toolchain": fixture["toolchain"],
        "fixture_sha256": fixture["fixture_sha256"],
        "command_sha256": _sha(list(command)),
        "execution_identity": dict(execution_identity) if execution_identity is not None else None,
        "artifacts": dict(artifacts)
        if artifacts is not None
        else {
            "golden_source_sha256": fixture["golden"]["sha256"],
            "migrated_source_sha256": None,
            "report_sha256": None,
            "output_roster_sha256": None,
        },
        "observed": dict(observed),
        "failure_reasons": normalized_reasons,
    }
    result = {**body, "result_sha256": _sha(body)}
    return validate_f5_migration_result(
        result,
        fixture=fixture,
        workspace_root=workspace_root,
    )


def run_f5_migration_fixture(
    *,
    fixture: Mapping[str, Any],
    workspace_root: Path,
    legacy_root: Path,
    base_root: Path,
    metis_root: Path,
    run_nonce: str,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Run one sealed F-5 fixture with explicit synthetic paths only.

    The caller owns the workspace and can confine it to ignored artifacts or a
    disposable sandbox.  No command is executed when the fixture, hashes, or
    path containment checks fail.
    """

    sealed = validate_f5_fixture(fixture)
    if type(run_nonce) is not str or _NONCE_RE.fullmatch(run_nonce) is None:
        raise F5FixtureError("F-5 run nonce must be 32-byte lowercase hex")
    empty_observed = _observed(
        "", "", None, expected_endpoint=sealed["golden"]["expected_endpoint"]
    )
    execution_identity: Mapping[str, str] | None = None
    command: list[str] = []
    try:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
            raise F5MigrationError("F-5 timeout must be an integer between 1 and 600 seconds")
        workspace = workspace_root.resolve()
        legacy = _contained(workspace, legacy_root, "legacy root")
        base = _contained(workspace, base_root, "base root")
        if _tree_sha256(legacy, frozenset({".json"})) != sealed["legacy_source"]["tree_sha256"]:
            return _result(
                sealed, empty_observed, ["source_hash_mismatch"], [], run_nonce=run_nonce
            )
        if (
            _tree_sha256(base, frozenset({".metis", ".json", ".toml"}))
            != sealed["base_source"]["tree_sha256"]
        ):
            return _result(sealed, empty_observed, ["base_hash_mismatch"], [], run_nonce=run_nonce)
        golden = _contained(base, base / sealed["golden"]["path"], "golden path")
        if not golden.is_file() or golden.is_symlink():
            return _result(
                sealed, empty_observed, ["golden_hash_mismatch"], [], run_nonce=run_nonce
            )
        golden_bytes = golden.read_bytes()
        if _bytes_sha(golden_bytes) != sealed["golden"]["sha256"]:
            return _result(
                sealed, empty_observed, ["golden_hash_mismatch"], [], run_nonce=run_nonce
            )
        if not golden_bytes.startswith(b"metis 0.43\n"):
            return _result(sealed, empty_observed, ["golden_not_043"], [], run_nonce=run_nonce)
        if _declared_golden_endpoints(golden_bytes) != [sealed["golden"]["expected_endpoint"]]:
            return _result(
                sealed,
                empty_observed,
                ["golden_endpoint_mismatch"],
                [],
                run_nonce=run_nonce,
            )

        root, node, execution_identity = _pinned_execution_identity(metis_root)
        tooling = root / "tooling"
        cli = tooling / "src/migrate/cli.ts"
        checkout_status_before = _git_full_status(root)
        output_root = workspace / "f5-output" / sealed["fixture_id"].replace("/", "_") / run_nonce
        if output_root.exists() or output_root.is_symlink():
            return _result(
                sealed,
                empty_observed,
                ["output_not_fresh"],
                [],
                run_nonce=run_nonce,
                execution_identity=execution_identity,
            )
        output_root.mkdir(parents=True, exist_ok=False)
        command = [
            str(node),
            "--import",
            "tsx",
            str(cli),
            "--endpoint",
            sealed["legacy_source"]["endpoint_id"],
            "--legacy",
            str(legacy),
            "--base",
            str(base),
            "--out",
            str(output_root),
            "--check",
        ]
        temp_root = workspace / "f5-tmp" / run_nonce
        temp_root.mkdir(parents=True, exist_ok=False)
        completed = subprocess.run(
            command,
            cwd=tooling,
            env={
                "PATH": str(node.parent),
                "TMPDIR": str(temp_root),
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "NO_COLOR": "1",
            },
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
        observed = _observed(
            completed.stdout,
            completed.stderr,
            completed.returncode,
            expected_endpoint=sealed["golden"]["expected_endpoint"],
        )
        reasons: list[str] = []
        if completed.returncode != 0:
            reasons.append("process_failed")
        if (observed["migrated_recompiled"], observed["migrated_total"]) != (1, 1):
            reasons.append("migrated_not_1_of_1")
        if observed["diagnostics_seen"]:
            reasons.append("diagnostics_present")
        if (observed["parity_ok"], observed["parity_diverge"]) != (1, 0):
            reasons.append("parity_not_1_ok_0_diverge")
        if observed["ir_parity_ok_count"] != 1:
            reasons.append("missing_ir_parity_ok")
        if observed["non_promote_seen"]:
            reasons.append("non_promote_present")
        expected_source = output_root / sealed["golden"]["path"]
        expected_report = output_root / "migrate-report.md"
        output_roster_sha256: str | None = None
        try:
            expected_source, expected_report, output_roster_sha256 = _inspect_output_tree(
                output_root,
                golden_path=sealed["golden"]["path"],
            )
        except F5MigrationError:
            reasons.append("output_roster_mismatch")
        migrated_source_sha256: str | None = None
        report_sha256: str | None = None
        if expected_source.is_file() and not expected_source.is_symlink():
            migrated_source_sha256 = _file_sha(expected_source)
            if migrated_source_sha256 != sealed["golden"]["sha256"]:
                reasons.append("migrated_source_mismatch")
        else:
            reasons.append("output_roster_mismatch")
        if expected_report.is_file() and not expected_report.is_symlink():
            report_sha256 = _file_sha(expected_report)
        else:
            reasons.append("output_roster_mismatch")
        artifacts = {
            "golden_source_sha256": sealed["golden"]["sha256"],
            "migrated_source_sha256": migrated_source_sha256,
            "report_sha256": report_sha256,
            "output_roster_sha256": output_roster_sha256,
        }
        try:
            _, _, execution_after = _pinned_execution_identity(root)
        except F5MigrationError:
            reasons.append("toolchain_mismatch")
        else:
            if execution_after != execution_identity:
                reasons.append("toolchain_mismatch")
        if _git_full_status(root) != checkout_status_before:
            reasons.append("checkout_changed")
        if _tree_sha256(legacy, frozenset({".json"})) != sealed["legacy_source"]["tree_sha256"]:
            reasons.append("source_hash_mismatch")
        if (
            _tree_sha256(base, frozenset({".metis", ".json", ".toml"}))
            != sealed["base_source"]["tree_sha256"]
        ):
            reasons.append("base_hash_mismatch")
        return _result(
            sealed,
            observed,
            reasons,
            command,
            run_nonce=run_nonce,
            execution_identity=execution_identity,
            artifacts=artifacts,
            workspace_root=workspace,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return _result(
            sealed,
            _observed(
                stdout,
                stderr,
                None,
                expected_endpoint=sealed["golden"]["expected_endpoint"],
            ),
            ["runner_timeout"],
            command,
            run_nonce=run_nonce,
            execution_identity=execution_identity,
        )
    except F5MigrationError as error:
        reason = "toolchain_mismatch" if "toolchain" in str(error).lower() else "fixture_invalid"
        return _result(
            sealed,
            empty_observed,
            [reason],
            command,
            run_nonce=run_nonce,
            execution_identity=execution_identity,
        )


def validate_f5_migration_result(
    value: Any,
    *,
    fixture: Mapping[str, Any],
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Validate a result against its fixture and, when green, its local files."""

    try:
        raw = _exact_mapping(
            value,
            frozenset(
                {
                    "schema_version",
                    "fixture_id",
                    "family",
                    "run_nonce",
                    "status",
                    "runner_checks_passed",
                    "evidence_class",
                    "promotion_eligible",
                    "authority_gap",
                    "toolchain",
                    "fixture_sha256",
                    "command_sha256",
                    "execution_identity",
                    "artifacts",
                    "observed",
                    "failure_reasons",
                    "result_sha256",
                }
            ),
            "F-5 result",
        )
        if _schema_errors(raw, "f5-migration-result.schema.json"):
            raise F5ResultError("F-5 result does not satisfy its schema")
        if type(raw["run_nonce"]) is not str or _NONCE_RE.fullmatch(raw["run_nonce"]) is None:
            raise F5ResultError("F-5 result run nonce is invalid")
        reasons = raw["failure_reasons"]
        if len(reasons) != len(set(reasons)) or any(
            reason not in _FAILURE_REASONS for reason in reasons
        ):
            raise F5ResultError("F-5 result failure reasons are invalid")
        if (
            raw["evidence_class"] != "local_runner_observation"
            or raw["promotion_eligible"] is not False
            or raw["authority_gap"] != "protected_execution_receipt_missing"
        ):
            raise F5ResultError("F-5 result cannot claim protected or promotional authority")
        if raw["runner_checks_passed"] != (not reasons) or raw["status"] != (
            "runner_checks_passed" if raw["runner_checks_passed"] else "blocked"
        ):
            raise F5ResultError("F-5 result status disagrees with failure reasons")
        if raw["runner_checks_passed"]:
            observed = raw["observed"]
            artifacts = raw["artifacts"]
            if (
                observed["process_exit_code"] != 0
                or observed["report_summary_count"] != 1
                or (observed["migrated_recompiled"], observed["migrated_total"]) != (1, 1)
                or (observed["parity_ok"], observed["parity_diverge"]) != (1, 0)
                or observed["ir_parity_ok_count"] != 1
                or observed["diagnostics_seen"] is not False
                or observed["non_promote_seen"] is not False
                or raw["execution_identity"] != _registered_execution_identity()
                or artifacts["golden_source_sha256"] != fixture["golden"]["sha256"]
                or artifacts["migrated_source_sha256"] != fixture["golden"]["sha256"]
                or not all(
                    type(artifacts[key]) is str and _HASH_RE.fullmatch(artifacts[key]) is not None
                    for key in ("report_sha256", "output_roster_sha256")
                )
            ):
                raise F5ResultError("F-5 green local result violates a required migration gate")
        body = {key: raw[key] for key in raw if key != "result_sha256"}
        if raw["result_sha256"] != _sha(body):
            raise F5ResultError("F-5 result hash does not match its canonical body")
        normalized = dict(raw)
        sealed = validate_f5_fixture(fixture)
        for key in ("fixture_id", "toolchain", "fixture_sha256"):
            if normalized[key] != sealed[key]:
                raise F5ResultError(f"F-5 result {key} differs from its fixture")
        if normalized["artifacts"]["golden_source_sha256"] != sealed["golden"]["sha256"]:
            raise F5ResultError("F-5 result golden source differs from its fixture")
        if normalized["runner_checks_passed"]:
            if workspace_root is None:
                raise F5ResultError(
                    "F-5 green local result requires its workspace for artifact recomputation"
                )
            workspace = workspace_root.resolve()
            output_root = _contained(
                workspace,
                workspace
                / "f5-output"
                / sealed["fixture_id"].replace("/", "_")
                / normalized["run_nonce"],
                "F-5 result output root",
            )
            try:
                migrated, report, roster_sha256 = _inspect_output_tree(
                    output_root,
                    golden_path=sealed["golden"]["path"],
                )
            except F5MigrationError as error:
                raise F5ResultError(
                    "F-5 result local artifacts are unavailable or invalid"
                ) from error
            artifacts = normalized["artifacts"]
            if (
                _file_sha(migrated) != artifacts["migrated_source_sha256"]
                or _file_sha(report) != artifacts["report_sha256"]
                or roster_sha256 != artifacts["output_roster_sha256"]
            ):
                raise F5ResultError("F-5 result local artifact hashes do not recompute")
        return normalized
    except F5ResultError:
        raise
    except F5MigrationError as error:
        raise F5ResultError(str(error)) from error
    except Exception as error:  # noqa: BLE001 - result is an untrusted boundary
        raise F5ResultError("F-5 result is malformed") from error
