"""Immutable Metis Brain toolchain identity and Git-object verifier.

This pin is deliberately independent from the historical catalog-maintenance
pin.  Brain compiler and retriever code can consume the frozen identity without
granting either component authority to write a tenant or to execute mutable
working-tree source.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

from metis_model1 import catalog_maintenance_pin as _sandbox_support
from metis_model1.oracles import _node_modules_sha256

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "schemas/metis-brain-toolchain-pin.schema.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/metis-brain-toolchain-pin-v1.json"
MAX_CONTRACT_BYTES = 2 * 1024 * 1024
MAX_NODE_BYTES = 512 * 1024 * 1024
MAX_JSON_DEPTH = 16
GIT_EXECUTABLE = Path("/usr/bin/git")
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
MAX_PROBE_STDOUT_BYTES = 4 * 1024 * 1024
MAX_PROBE_STDERR_BYTES = 128 * 1024
PROBE_TIMEOUT_SECONDS = 120

# Filled after the two immutable contract files are materialized.  Checking
# both digests prevents a caller from silently substituting a different schema
# or manifest while retaining the same public path.
SCHEMA_FILE_SHA256 = "sha256:83959b4d4ecff5194868363bbbbf7c0cddb4ac3ca7baff64d406ace6f1ea1d8c"
MANIFEST_FILE_SHA256 = "sha256:19a4169dc5590dd8727844cea76736c8189d3171ac4d69b6a24a78bb3e4687b9"

_OID_RE = r"^[0-9a-f]{40}$"
_SHA256_RE = r"^sha256:[0-9a-f]{64}$"
_EXPECTED_EVIDENCE = {
    "grammar": "tooling/src/language/metis.langium",
    "generated_ast": "tooling/src/language/generated/ast.ts",
    "generated_grammar": "tooling/src/language/generated/grammar.ts",
    "domain_resolver": "tooling/src/language/field-values.ts",
    "semantic_authority": "tooling/src/language/catalog-semantics.ts",
    "validator": "tooling/src/language/metis-validator.ts",
    "formatter": "tooling/src/language/metis-formatter.ts",
    "language_compiler_bridge": "tooling/src/language/metis-compile.ts",
    "compiler": "tooling/src/compiler/compile.ts",
    "ir_contract": "tooling/src/compiler/ir.ts",
    "retrieval_cli": "tooling/src/cli/catalog-domain.ts",
    "semantic_retrieval_oracle": "tooling/test/catalog-semantic.ts",
    "r8_description": "tooling/test/r8-description-invariant.ts",
    "r8_surface": "tooling/test/r8-semantic-surface.ts",
    "tooling_package": "tooling/package.json",
    "tooling_lock": "tooling/package-lock.json",
    "lossless_types": "tooling/src/lossless/types.ts",
    "lossless_inventory": "tooling/src/lossless/inventory.ts",
    "lossless_plan": "tooling/src/lossless/plan.ts",
    "lossless_apply": "tooling/src/lossless/apply.ts",
    "lossless_toolchain": "tooling/src/lossless/toolchain.ts",
    "lossless_cli": "tooling/src/cli/lossless.ts",
    "lossless_spec": "docs/design/lossless-renderer/spec.md",
    "lossless_api": "docs/design/lossless-renderer/api.md",
    "lossless_gate_roundtrip": "tooling/test/lossless-roundtrip-corpus.ts",
    "lossless_gate_adversarial": "tooling/test/lossless-adversarial.ts",
    "lossless_gate_editplan": "tooling/test/lossless-editplan.ts",
    "lossless_gate_minimal": "tooling/test/lossless-edit-minimal.ts",
    "lossless_gate_compile": "tooling/test/lossless-compile-proof.ts",
}
_EXPECTED_PROBES = {
    "typecheck": (
        "node",
        "node_modules/typescript/bin/tsc",
        "--noEmit",
        "-p",
        "tsconfig.probes.json",
    ),
    "semantic_retrieval": ("node", "--import", "tsx", "test/catalog-semantic.ts"),
    "r8_description": ("node", "--import", "tsx", "test/r8-description-invariant.ts"),
    "r8_surface": ("node", "--import", "tsx", "test/r8-semantic-surface.ts"),
    "lossless_roundtrip": ("node", "--import", "tsx", "test/lossless-roundtrip-corpus.ts"),
    "lossless_adversarial": ("node", "--import", "tsx", "test/lossless-adversarial.ts"),
    "lossless_editplan": ("node", "--import", "tsx", "test/lossless-editplan.ts"),
    "lossless_minimal": ("node", "--import", "tsx", "test/lossless-edit-minimal.ts"),
    "lossless_compile": ("node", "--import", "tsx", "test/lossless-compile-proof.ts"),
}
_EXPECTED_MARKERS = {
    "typecheck": None,
    "semantic_retrieval": "catalog semantic retrieval (schema 2): VERDE ✓",
    "r8_description": "R8 invariante (esteso a Catalog/Field/ValueItem/ListEntry): OK",
    "r8_surface": "superficie semantica: OK",
    "lossless_roundtrip": "LOSSLESS_ROUNDTRIP_CORPUS: VERDE ✓",
    "lossless_adversarial": "LOSSLESS_ADVERSARIAL: VERDE ✓",
    "lossless_editplan": "LOSSLESS_EDITPLAN: VERDE ✓",
    "lossless_minimal": "LOSSLESS_EDIT_MINIMAL: VERDE ✓",
    "lossless_compile": "LOSSLESS_COMPILE_PROOF: VERDE ✓",
}
_EXPECTED_NONCLAIMS = (
    "no_tenant_payload",
    "no_model_output",
    "no_training_authority",
    "no_accuracy_claim",
    "no_autonomous_writes",
    "nonpromotable",
)


class BrainToolchainPinError(ValueError):
    """Raised when the Brain toolchain pin cannot be proven exactly."""


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
        raise BrainToolchainPinError("pin is not canonical JSON data") from error


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """Return the content-addressed identity used by Brain bindings."""

    return "sha256:" + hashlib.sha256(_canonical(manifest)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BrainToolchainPinError("Brain toolchain pin contains duplicate JSON keys")
        result[key] = value
    return result


def _validate_json_tree(value: Any, *, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise BrainToolchainPinError("Brain toolchain pin nesting exceeds the contract bound")
    if isinstance(value, str):
        if any(
            ord(character) < 0x20
            or 0x7F <= ord(character) <= 0x9F
            or 0xD800 <= ord(character) <= 0xDFFF
            or 0xFDD0 <= ord(character) <= 0xFDEF
            or ord(character) & 0xFFFF in {0xFFFE, 0xFFFF}
            for character in value
        ):
            raise BrainToolchainPinError("Brain toolchain pin contains invalid Unicode")
    elif isinstance(value, Mapping):
        if len(value) > 64:
            raise BrainToolchainPinError("Brain toolchain pin object exceeds the item bound")
        for key, child in value.items():
            if not isinstance(key, str):
                raise BrainToolchainPinError("Brain toolchain pin object key is not text")
            _validate_json_tree(key, depth=depth + 1)
            _validate_json_tree(child, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 64:
            raise BrainToolchainPinError("Brain toolchain pin array exceeds the item bound")
        for child in value:
            _validate_json_tree(child, depth=depth + 1)


def _read_contract_file(path: Path, expected_sha256: str, label: str) -> bytes:
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size > MAX_CONTRACT_BYTES
        ):
            raise BrainToolchainPinError(f"{label} is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = opened.st_size + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        path_after = path.lstat()
    except BrainToolchainPinError:
        raise
    except OSError as error:
        raise BrainToolchainPinError(f"{label} is unavailable") from error
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
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if (
        identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(path_after)
        or len(raw) != before.st_size
        or digest != expected_sha256
    ):
        raise BrainToolchainPinError(f"{label} differs from its fixed digest")
    return raw


def _load_json(path: Path, expected_sha256: str, label: str) -> Any:
    raw = _read_contract_file(path, expected_sha256, label)
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                BrainToolchainPinError(f"{label} contains non-finite number: {constant}")
            ),
        )
    except BrainToolchainPinError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BrainToolchainPinError(f"{label} is not valid JSON") from error


def _safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BrainToolchainPinError(f"{label} is not a relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", "..", ".git"} for part in path.parts)
    ):
        raise BrainToolchainPinError(f"{label} is not a relative POSIX path")
    return value


def _exact_sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise BrainToolchainPinError(f"{label} must be an array")
    return value


def _validate_manifest_shape(manifest: Mapping[str, Any]) -> None:
    if set(manifest) != {
        "schema_version",
        "pin_id",
        "repository",
        "revision",
        "tree",
        "remote_url",
        "remote_ref",
        "language_version",
        "tooling_version",
        "runtime",
        "evidence",
        "probes",
        "policy",
        "nonclaims",
    }:
        raise BrainToolchainPinError("Brain toolchain pin field roster drifted")
    if (
        manifest["schema_version"] != 1
        or manifest["pin_id"] != "metis-brain-toolchain/2026-08-30-v1"
        or manifest["repository"] != "ares-matioska/metis"
        or manifest["revision"] != "2ad60b3c804fb1c45e45883b0479a46f660d98f6"
        or manifest["tree"] != "ea29b935934fadd5f99711c0470566a2484b35f6"
        or manifest["remote_url"] != "git@github.com:ttessarolo/metis.git"
        or manifest["remote_ref"] != "refs/remotes/origin/main"
        or manifest["language_version"] != "0.43"
        or manifest["tooling_version"] != "0.23.97"
        or type(manifest["schema_version"]) is not int
        or not isinstance(manifest["revision"], str)
        or not isinstance(manifest["tree"], str)
    ):
        raise BrainToolchainPinError("Brain toolchain pin identity drifted")
    if (
        re.fullmatch(_OID_RE, manifest["revision"]) is None
        or re.fullmatch(_OID_RE, manifest["tree"]) is None
    ):
        raise BrainToolchainPinError("Brain toolchain pin commit identity is malformed")
    runtime = manifest["runtime"]
    expected_runtime = {
        "node_version": "v22.22.3",
        "node_sha256": "sha256:5d9d3872911e2340a43b707962e68143de8a4e8d54628845c0c4f2de1fb7cd5c",
        "node_bytes": 112915776,
        "node_modules_sha256": (
            "sha256:1cea5f2f0371d3c57b9ef9787707bc1079f88dc697c7be2c6c247e4018f6e463"
        ),
        "langium_version": "4.3.0",
        "metis_language_version": "0.43",
        "grammar_sha256": "sha256:dbbb2cf98f870d854af9082cb8ee33595054e993d7831d662170aeea0db8db01",
        "package_sha256": "sha256:99584c57dff11fe4fe623fba3d3bcf96630e72f68aa0be8f4b67ad4f63b6b7af",
        "lock_sha256": "sha256:4a362a20ad10a44adfa1e8c73bbfd7b536fb3a8f71bc12fd54220547adfbf9dd",
    }
    if not isinstance(runtime, Mapping) or dict(runtime) != expected_runtime:
        raise BrainToolchainPinError("Brain runtime identity drifted")
    if not all(
        re.fullmatch(_SHA256_RE, value) for key, value in runtime.items() if key.endswith("sha256")
    ):
        raise BrainToolchainPinError("Brain runtime hash is malformed")
    evidence = _exact_sequence(manifest["evidence"], "evidence")
    if len(evidence) != len(_EXPECTED_EVIDENCE):
        raise BrainToolchainPinError("Brain evidence roster has an unexpected cardinality")
    ids: set[str] = set()
    paths: set[str] = set()
    oids: set[str] = set()
    for item in evidence:
        if not isinstance(item, Mapping) or set(item) != {"id", "path", "blob_oid", "sha256"}:
            raise BrainToolchainPinError("Brain evidence entry shape drifted")
        identifier = item["id"]
        path = _safe_relative(item["path"], "evidence path")
        if (
            not isinstance(identifier, str)
            or identifier not in _EXPECTED_EVIDENCE
            or _EXPECTED_EVIDENCE[identifier] != path
            or identifier in ids
            or path in paths
            or not isinstance(item["blob_oid"], str)
            or re.fullmatch(_OID_RE, item["blob_oid"]) is None
            or item["blob_oid"] in oids
            or not isinstance(item["sha256"], str)
            or re.fullmatch(_SHA256_RE, item["sha256"]) is None
        ):
            raise BrainToolchainPinError("Brain evidence identity drifted")
        ids.add(identifier)
        paths.add(path)
        oids.add(item["blob_oid"])
    if ids != set(_EXPECTED_EVIDENCE):
        raise BrainToolchainPinError("Brain evidence roster is incomplete")
    grammar_evidence = next(item for item in manifest["evidence"] if item["id"] == "grammar")
    if grammar_evidence["sha256"] != manifest["runtime"]["grammar_sha256"]:
        raise BrainToolchainPinError("Brain grammar digest differs from runtime identity")
    probes = _exact_sequence(manifest["probes"], "probes")
    if len(probes) != len(_EXPECTED_PROBES):
        raise BrainToolchainPinError("Brain probe roster has an unexpected cardinality")
    probe_ids: set[str] = set()
    for probe in probes:
        if not isinstance(probe, Mapping) or set(probe) != {"id", "cwd", "argv", "success_marker"}:
            raise BrainToolchainPinError("Brain probe entry shape drifted")
        identifier = probe["id"]
        argv = _exact_sequence(probe["argv"], "probe argv")
        if (
            not isinstance(identifier, str)
            or identifier not in _EXPECTED_PROBES
            or identifier in probe_ids
            or probe["cwd"] != "tooling"
            or tuple(argv) != _EXPECTED_PROBES[identifier]
            or probe["success_marker"] != _EXPECTED_MARKERS[identifier]
        ):
            raise BrainToolchainPinError("Brain probe identity drifted")
        probe_ids.add(identifier)
    if probe_ids != set(_EXPECTED_PROBES):
        raise BrainToolchainPinError("Brain probe roster is incomplete")
    expected_policy = {
        "git_objects_only": True,
        "remote_ref_contains_revision_required": True,
        "tracked_worktree_excluded": True,
        "untracked_worktree_excluded": True,
        "archive_execution": True,
        "network_denied": True,
        "external_repository_writes_denied": True,
    }
    if manifest["policy"] != expected_policy:
        raise BrainToolchainPinError("Brain toolchain policy drifted")
    if tuple(manifest["nonclaims"]) != _EXPECTED_NONCLAIMS:
        raise BrainToolchainPinError("Brain toolchain nonclaims drifted")


def load_metis_brain_toolchain_pin(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Load and validate the immutable Brain contract and its fixed schema."""

    base = Path(root).resolve(strict=True)
    schema = _load_json(
        base / SCHEMA_PATH.relative_to(PROJECT_ROOT), SCHEMA_FILE_SHA256, "Brain pin schema"
    )
    manifest = _load_json(
        base / MANIFEST_PATH.relative_to(PROJECT_ROOT), MANIFEST_FILE_SHA256, "Brain pin manifest"
    )
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:  # noqa: BLE001 - schema failures close the gate
        raise BrainToolchainPinError("Brain pin schema is invalid") from error
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise BrainToolchainPinError(f"Brain pin schema mismatch at {location}: {first.message}")
    if not isinstance(manifest, dict):
        raise BrainToolchainPinError("Brain pin manifest must be an object")
    _validate_json_tree(manifest)
    _validate_manifest_shape(manifest)
    return manifest


def validate_metis_brain_toolchain_pin_contract(root: Path = PROJECT_ROOT) -> list[str]:
    try:
        load_metis_brain_toolchain_pin(root)
        return []
    except (
        BrainToolchainPinError,
        OSError,
        TypeError,
        ValueError,
        UnicodeError,
        RecursionError,
    ) as error:
        return [str(error)]


@dataclass(frozen=True, slots=True)
class BrainToolchainIdentity:
    """Typed immutable identity shared by Brain compiler and retriever."""

    pin_id: str
    repository: str
    revision: str
    tree: str
    language_version: str
    tooling_version: str
    node_version: str
    node_sha256: str
    node_bytes: int
    node_modules_sha256: str
    langium_version: str
    metis_language_version: str
    grammar_sha256: str
    package_sha256: str
    lock_sha256: str
    manifest_sha256: str

    @property
    def toolchain_binding(self) -> str:
        return self.manifest_sha256

    def as_dict(self) -> dict[str, Any]:
        """Return a detached serialization suitable for receipts."""

        return asdict(self)


MetisBrainToolchainIdentity = BrainToolchainIdentity


def brain_toolchain_identity_from_pin(pin: Mapping[str, Any]) -> BrainToolchainIdentity:
    """Project a validated manifest into an immutable compiler/retriever identity."""

    _validate_manifest_shape(pin)
    runtime = pin["runtime"]
    return BrainToolchainIdentity(
        pin_id=pin["pin_id"],
        repository=pin["repository"],
        revision=pin["revision"],
        tree=pin["tree"],
        language_version=pin["language_version"],
        tooling_version=pin["tooling_version"],
        node_version=runtime["node_version"],
        node_sha256=runtime["node_sha256"],
        node_bytes=runtime["node_bytes"],
        node_modules_sha256=runtime["node_modules_sha256"],
        langium_version=runtime["langium_version"],
        metis_language_version=runtime["metis_language_version"],
        grammar_sha256=runtime["grammar_sha256"],
        package_sha256=runtime["package_sha256"],
        lock_sha256=runtime["lock_sha256"],
        manifest_sha256=manifest_sha256(pin),
    )


def load_metis_brain_toolchain_identity(root: Path = PROJECT_ROOT) -> BrainToolchainIdentity:
    return brain_toolchain_identity_from_pin(load_metis_brain_toolchain_pin(root))


def _git(root: Path, *args: str, text: bool = True) -> str | bytes:
    try:
        result = subprocess.run(
            [str(GIT_EXECUTABLE), "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=text,
            timeout=30,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
            },
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BrainToolchainPinError("pinned Metis Git verification failed") from error
    return result.stdout.strip() if text else result.stdout


def _verify_node(node_path: Path, runtime: Mapping[str, Any]) -> bytes:
    try:
        node = Path(node_path).resolve(strict=True)
        descriptor = os.open(node, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError as error:
        raise BrainToolchainPinError("pinned Node binary is unavailable") from error
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    except OSError as error:
        raise BrainToolchainPinError("cannot read the pinned Node binary") from error
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o755
        or before.st_nlink != 1
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or len(raw) != runtime["node_bytes"]
        or "sha256:" + hashlib.sha256(raw).hexdigest() != runtime["node_sha256"]
    ):
        raise BrainToolchainPinError("Node binary differs from the Brain pin")
    return raw


def verify_metis_brain_toolchain_pin(
    metis_root: Path,
    node_path: Path,
    *,
    execute_probes: bool = False,
) -> dict[str, Any]:
    """Verify pinned Git objects and local runtime identity.

    Probes are represented and checked as an exact roster at load time.  The
    default verification is intentionally static so Brain can bind identity at
    startup without executing arbitrary source; a future probe runner may use
    the same archive policy without changing this identity contract.
    """

    manifest = load_metis_brain_toolchain_pin()
    root = Path(metis_root).resolve(strict=True)
    if not root.is_dir():
        raise BrainToolchainPinError("Metis root is not a directory")
    revision = manifest["revision"]
    if _git(root, "rev-parse", revision) != revision:
        raise BrainToolchainPinError("pinned Metis revision is unavailable")
    if _git(root, "rev-parse", f"{revision}^{{tree}}") != manifest["tree"]:
        raise BrainToolchainPinError("pinned Metis tree differs from the Brain pin")
    remote_revision = str(_git(root, "rev-parse", manifest["remote_ref"]))
    if re.fullmatch(_OID_RE, remote_revision) is None:
        raise BrainToolchainPinError("Metis remote main ref is malformed")
    try:
        _git(root, "merge-base", "--is-ancestor", revision, remote_revision)
    except BrainToolchainPinError as error:
        raise BrainToolchainPinError("Metis remote main does not contain the Brain pin") from error

    verified: list[dict[str, str]] = []
    for item in manifest["evidence"]:
        row = str(_git(root, "ls-tree", revision, "--", item["path"])).split()
        if row != ["100644", "blob", item["blob_oid"], item["path"]]:
            raise BrainToolchainPinError(f"Brain evidence Git identity drifted: {item['path']}")
        raw = _git(root, "cat-file", "blob", item["blob_oid"], text=False)
        assert isinstance(raw, bytes)
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        if digest != item["sha256"]:
            raise BrainToolchainPinError(f"Brain evidence content drifted: {item['path']}")
        verified.append({"id": item["id"], "path": item["path"], "sha256": digest})

    package_raw = _git(root, "cat-file", "blob", f"{revision}:tooling/package.json", text=False)
    lock_raw = _git(root, "cat-file", "blob", f"{revision}:tooling/package-lock.json", text=False)
    assert isinstance(package_raw, bytes) and isinstance(lock_raw, bytes)
    if "sha256:" + hashlib.sha256(package_raw).hexdigest() != manifest["runtime"]["package_sha256"]:
        raise BrainToolchainPinError("tooling/package.json differs from the Brain pin")
    if "sha256:" + hashlib.sha256(lock_raw).hexdigest() != manifest["runtime"]["lock_sha256"]:
        raise BrainToolchainPinError("tooling/package-lock.json differs from the Brain pin")
    try:
        package = json.loads(package_raw)
        lock = json.loads(lock_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BrainToolchainPinError("pinned tooling metadata is not valid JSON") from error
    if (
        package.get("version") != manifest["tooling_version"]
        or lock.get("version") != manifest["tooling_version"]
        or lock.get("packages", {}).get("", {}).get("version") != manifest["tooling_version"]
        or lock.get("packages", {}).get("node_modules/langium", {}).get("version")
        != manifest["runtime"]["langium_version"]
        or manifest["runtime"]["metis_language_version"] != manifest["language_version"]
    ):
        raise BrainToolchainPinError("tooling package and lock versions differ from the Brain pin")

    runtime = manifest["runtime"]
    node_bytes = _verify_node(Path(node_path), runtime)
    modules = (root / "tooling/node_modules").resolve(strict=True)
    modules_sha256 = "sha256:" + _node_modules_sha256(modules)
    if modules_sha256 != runtime["node_modules_sha256"]:
        raise BrainToolchainPinError("tooling node_modules differs from the Brain pin")
    probe_reports: list[dict[str, Any]] = []
    if execute_probes:
        probe_reports = _run_brain_archive_probes(
            manifest,
            root,
            node_bytes,
            remote_revision=remote_revision,
            modules_sha256=modules_sha256,
        )
    identity = brain_toolchain_identity_from_pin(manifest)
    receipt_sha256 = manifest_sha256(probe_reports) if execute_probes else None
    return {
        "status": "VERIFIED",
        "identity": identity,
        "pin_id": identity.pin_id,
        "revision": identity.revision,
        "tree": identity.tree,
        "remote_ref_revision": remote_revision,
        "remote_ref_contains_revision_verified": True,
        "toolchain_binding": identity.toolchain_binding,
        "evidence_in": len(manifest["evidence"]),
        "evidence_out": len(verified),
        "evidence_distinct": len({item["id"] for item in verified}),
        "evidence_gaps": len(manifest["evidence"]) - len(verified),
        "probes_in": len(manifest["probes"]),
        "probes_out": len(probe_reports),
        "probes_distinct": len({item["id"] for item in probe_reports}),
        "probes_gaps": len(manifest["probes"]) - len(probe_reports),
        "probes_executed": execute_probes,
        "probe_reports": probe_reports,
        "probe_receipt_sha256": receipt_sha256,
        "node_bytes_verified": len(node_bytes),
        "manifest_sha256": identity.manifest_sha256,
        "nonclaims": manifest["nonclaims"],
    }


def _run_brain_archive_probes(
    manifest: Mapping[str, Any],
    metis_root: Path,
    node_bytes: bytes,
    *,
    remote_revision: str,
    modules_sha256: str,
) -> list[dict[str, Any]]:
    """Run the exact probe roster against an immutable Git archive."""

    revision = manifest["revision"]
    probe_reports: list[dict[str, Any]] = []
    try:
        archive = _git(metis_root, "archive", "--format=tar", revision, text=False)
        assert isinstance(archive, bytes)
        archive_sha256 = "sha256:" + hashlib.sha256(archive).hexdigest()
        with tempfile.TemporaryDirectory(prefix="metis-model1-brain-pin-") as temp:
            snapshot = Path(temp).resolve()
            _sandbox_support._safe_extract_archive(archive, snapshot)
            tooling = snapshot / "tooling"
            source_modules = (metis_root / "tooling/node_modules").resolve(strict=True)
            snapshot_modules = tooling / "node_modules"
            shutil.copytree(source_modules, snapshot_modules, symlinks=True)
            if "sha256:" + _node_modules_sha256(snapshot_modules) != modules_sha256:
                raise BrainToolchainPinError(
                    "copied tooling node_modules differs from the Brain pin"
                )
            node = snapshot / "pinned-node"
            node.write_bytes(node_bytes)
            node.chmod(0o500)
            scratch = (snapshot / "probe-scratch").resolve()
            scratch.mkdir(mode=0o700)
            home = Path.home().resolve(strict=True)
            policy = " ".join(
                (
                    "(version 1)",
                    "(allow default)",
                    "(deny file-write*)",
                    "(allow file-write* (subpath " + json.dumps(str(scratch)) + "))",
                    "(deny network*)",
                    f"(deny file-read* (subpath {json.dumps(str(home))}))",
                    f"(allow file-read* (subpath {json.dumps(str(snapshot))}))",
                )
            )
            _sandbox_support._assert_sandbox_boundaries(snapshot, policy)
            probe_env = _sandbox_support._probe_process_environment()
            probe_env.update({"TMPDIR": str(scratch), "TMP": str(scratch), "TEMP": str(scratch)})
            version = subprocess.run(
                [str(SANDBOX_EXEC), "-p", policy, str(node), "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
                env=probe_env,
            ).stdout.strip()
            if version != manifest["runtime"]["node_version"]:
                raise BrainToolchainPinError("copied Node version differs from the Brain pin")
            for probe in manifest["probes"]:
                argv = [str(node), *probe["argv"][1:]]
                completed = subprocess.run(
                    [str(SANDBOX_EXEC), "-p", policy, *argv],
                    cwd=tooling,
                    check=False,
                    capture_output=True,
                    timeout=PROBE_TIMEOUT_SECONDS,
                    env=probe_env,
                )
                if len(completed.stdout) > MAX_PROBE_STDOUT_BYTES:
                    raise BrainToolchainPinError(f"probe stdout cap exceeded: {probe['id']}")
                if len(completed.stderr) > MAX_PROBE_STDERR_BYTES:
                    raise BrainToolchainPinError(f"probe stderr cap exceeded: {probe['id']}")
                try:
                    stdout = completed.stdout.decode("utf-8", errors="strict")
                    stderr = completed.stderr.decode("utf-8", errors="strict")
                except UnicodeDecodeError as error:
                    raise BrainToolchainPinError(
                        f"probe output is not UTF-8: {probe['id']}"
                    ) from error
                marker = probe["success_marker"]
                if completed.returncode != 0 or (marker is not None and marker not in stdout):
                    raise BrainToolchainPinError(
                        f"Brain probe failed: {probe['id']} "
                        f"(exit={completed.returncode}, stderr_sha256="
                        f"sha256:{hashlib.sha256(stderr.encode('utf-8')).hexdigest()}, "
                        f"stderr={stderr[:512]!r})"
                    )
                probe_reports.append(
                    {
                        "id": probe["id"],
                        "exit_code": completed.returncode,
                        "stdout_sha256": (
                            "sha256:" + hashlib.sha256(stdout.encode("utf-8")).hexdigest()
                        ),
                        "stderr_sha256": (
                            "sha256:" + hashlib.sha256(stderr.encode("utf-8")).hexdigest()
                        ),
                        "archive_sha256": archive_sha256,
                    }
                )
            if "sha256:" + _node_modules_sha256(snapshot_modules) != modules_sha256:
                raise BrainToolchainPinError("Brain probes changed copied node_modules")
        if _git(metis_root, "rev-parse", revision) != revision:
            raise BrainToolchainPinError("Metis revision changed during Brain probes")
        if _git(metis_root, "rev-parse", f"{revision}^{{tree}}") != manifest["tree"]:
            raise BrainToolchainPinError("Metis tree changed during Brain probes")
        if str(_git(metis_root, "rev-parse", manifest["remote_ref"])) != remote_revision:
            raise BrainToolchainPinError("Metis remote ref changed during Brain probes")
        if "sha256:" + _node_modules_sha256(source_modules) != modules_sha256:
            raise BrainToolchainPinError("source node_modules changed during Brain probes")
        return probe_reports
    except BrainToolchainPinError:
        raise
    except (OSError, UnicodeDecodeError, subprocess.SubprocessError) as error:
        raise BrainToolchainPinError("Brain archive probe execution failed") from error


# Short aliases keep the contract convenient at Brain call sites while the
# explicit names above remain the canonical public API for this file.
load_brain_toolchain_pin = load_metis_brain_toolchain_pin
validate_brain_toolchain_pin_contract = validate_metis_brain_toolchain_pin_contract
load_brain_toolchain_identity = load_metis_brain_toolchain_identity
verify_brain_toolchain_pin = verify_metis_brain_toolchain_pin


__all__ = [
    "BrainToolchainIdentity",
    "BrainToolchainPinError",
    "MANIFEST_PATH",
    "MetisBrainToolchainIdentity",
    "SCHEMA_PATH",
    "brain_toolchain_identity_from_pin",
    "load_brain_toolchain_identity",
    "load_brain_toolchain_pin",
    "load_metis_brain_toolchain_identity",
    "load_metis_brain_toolchain_pin",
    "manifest_sha256",
    "validate_metis_brain_toolchain_pin_contract",
    "validate_brain_toolchain_pin_contract",
    "verify_brain_toolchain_pin",
    "verify_metis_brain_toolchain_pin",
]
