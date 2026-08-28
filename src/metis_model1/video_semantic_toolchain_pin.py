"""Git-object-bound verifier for the Metis semantic retrieval delivery.

The historical catalog-maintenance pin remains immutable.  This successor pin
binds the first-class catalog semantics, structured sync and retrieval schema 2
to one promoted Metis commit.  Probes run from an archived snapshot; the
upstream working tree is never executed or modified.
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
from pathlib import Path, PurePosixPath
from typing import Any

import metis_model1.catalog_maintenance_pin as legacy_pin

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "manifests/video-semantic-toolchain-pin-v1.json"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_STDOUT_BYTES = 8 * 1024 * 1024
MAX_STDERR_BYTES = 256 * 1024
PROBE_TIMEOUT_SECONDS = 240
MAX_MANIFEST_DEPTH = 16
MAX_EVIDENCE_ITEMS = 15
MAX_PROBE_ITEMS = 7
MAX_ARGV_ITEMS = 16
MAX_NODE_BYTES = 512 * 1024 * 1024
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_EXPECTED_TOP_LEVEL = {
    "schema_version",
    "pin_id",
    "repository",
    "revision",
    "tree",
    "remote_url",
    "remote_ref",
    "language_version",
    "retrieval_schema",
    "delivery_ancestors",
    "runtime",
    "full_corpus_dependency",
    "evidence",
    "probes",
    "expected_denominators",
    "policy",
    "nonclaims",
}
_EXPECTED_EVIDENCE = {
    "retrieval_contract": "docs/design/catalog-values/retrieval-api.md",
    "grammar": "tooling/src/language/metis.langium",
    "generated_ast": "tooling/src/language/generated/ast.ts",
    "semantic_authority": "tooling/src/language/catalog-semantics.ts",
    "validator": "tooling/src/language/metis-validator.ts",
    "structured_sync": "tooling/src/cli/catalog-sync-values.ts",
    "retrieval_cli": "tooling/src/cli/catalog-domain.ts",
    "semantic_retrieval_oracle": "tooling/test/catalog-semantic.ts",
    "retrieval_oracle": "tooling/test/catalog-domain.ts",
    "r8_description": "tooling/test/r8-description-invariant.ts",
    "r8_surface": "tooling/test/r8-semantic-surface.ts",
    "sync_oracle": "tooling/test/catalog-sync-values-merge.ts",
    "full_corpus_oracle": "tooling/test/full-corpus-grammar-compat.ts",
    "test_chain": "tooling/package.json",
    "tooling_lock": "tooling/package-lock.json",
}
_EXPECTED_PROBES = {
    "typecheck",
    "semantic_retrieval",
    "catalog_retrieval",
    "r8_description",
    "r8_surface",
    "structured_sync",
    "full_corpus",
}
_REQUIRED_TEST_CHAIN = (
    "test/catalog-semantic.ts",
    "test/catalog-domain.ts",
    "test/r8-description-invariant.ts",
    "test/r8-semantic-surface.ts",
    "test/catalog-sync-values-merge.ts",
    "test/full-corpus-grammar-compat.ts",
)
_EXPECTED_REMOTE_URL = "git@github.com:ttessarolo/metis.git"
_EXPECTED_NONCLAIMS = (
    "no_tenant_semantics",
    "no_live_census",
    "no_canonical_patch",
    "no_model_output",
    "no_training_authority",
    "no_accuracy_claim",
)
_EXPECTED_PROBE_ARGV = {
    "typecheck": (
        "node",
        "node_modules/typescript/bin/tsc",
        "--noEmit",
        "-p",
        "tsconfig.probes.json",
    ),
    "semantic_retrieval": ("node", "--import", "tsx", "test/catalog-semantic.ts"),
    "catalog_retrieval": ("node", "--import", "tsx", "test/catalog-domain.ts"),
    "r8_description": ("node", "--import", "tsx", "test/r8-description-invariant.ts"),
    "r8_surface": ("node", "--import", "tsx", "test/r8-semantic-surface.ts"),
    "structured_sync": ("node", "--import", "tsx", "test/catalog-sync-values-merge.ts"),
    "full_corpus": ("node", "--import", "tsx", "test/full-corpus-grammar-compat.ts"),
}
_EXPECTED_PROBE_MARKERS = {
    "typecheck": None,
    "semantic_retrieval": "catalog semantic retrieval (schema 2): VERDE ✓",
    "catalog_retrieval": "catalog:describe / catalog:values — API di retrieval: VERDE ✓",
    "r8_description": "R8 invariante (esteso a Catalog/Field/ValueItem/ListEntry): OK",
    "r8_surface": "superficie semantica: OK",
    "structured_sync": "catalog:sync-values merge (G2): VERDE ✓",
    "full_corpus": "FULL_CORPUS_GRAMMAR_COMPAT: VERDE ✓",
}


class VideoSemanticToolchainPinError(ValueError):
    """The successor toolchain pin failed closed."""


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
        raise VideoSemanticToolchainPinError("pin is not canonical JSON data") from error


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(manifest)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VideoSemanticToolchainPinError("toolchain pin contains duplicate JSON keys")
        result[key] = value
    return result


def _validate_json_tree(value: Any, *, depth: int = 0) -> None:
    if depth > MAX_MANIFEST_DEPTH:
        raise VideoSemanticToolchainPinError("toolchain pin nesting exceeds the contract bound")
    if isinstance(value, str):
        for character in value:
            codepoint = ord(character)
            if (
                codepoint < 0x20
                or 0x7F <= codepoint <= 0x9F
                or 0xD800 <= codepoint <= 0xDFFF
                or 0xFDD0 <= codepoint <= 0xFDEF
                or codepoint & 0xFFFF in {0xFFFE, 0xFFFF}
            ):
                raise VideoSemanticToolchainPinError(
                    "toolchain pin contains a control or non-scalar Unicode character"
                )
        return
    if isinstance(value, Mapping):
        if len(value) > 64:
            raise VideoSemanticToolchainPinError("toolchain pin object exceeds the item bound")
        for key, child in value.items():
            if not isinstance(key, str):
                raise VideoSemanticToolchainPinError("toolchain pin object key is not text")
            _validate_json_tree(key, depth=depth + 1)
            _validate_json_tree(child, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > MAX_EVIDENCE_ITEMS + MAX_PROBE_ITEMS + MAX_ARGV_ITEMS:
            raise VideoSemanticToolchainPinError("toolchain pin array exceeds the item bound")
        for child in value:
            _validate_json_tree(child, depth=depth + 1)


def _safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise VideoSemanticToolchainPinError(f"{label} is not a relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", "..", ".git"} for part in path.parts)
    ):
        raise VideoSemanticToolchainPinError(f"{label} is not a relative POSIX path")
    return value


def _read_manifest(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    path = root.resolve(strict=True) / MANIFEST_PATH.relative_to(PROJECT_ROOT)
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size > MAX_MANIFEST_BYTES
        ):
            raise VideoSemanticToolchainPinError("toolchain pin is not a bounded regular file")
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
    except OSError as error:
        raise VideoSemanticToolchainPinError("toolchain pin is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity = lambda item: (  # noqa: E731 - immutable stat identity
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
        raise VideoSemanticToolchainPinError("toolchain pin changed while read")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                VideoSemanticToolchainPinError(
                    f"toolchain pin contains non-finite number: {constant}"
                )
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VideoSemanticToolchainPinError("toolchain pin is not JSON") from error
    if not isinstance(value, dict):
        raise VideoSemanticToolchainPinError("toolchain pin must be an object")
    _validate_json_tree(value)
    return value


def _exact_sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise VideoSemanticToolchainPinError(f"{label} must be an array")
    return value


def load_video_semantic_toolchain_pin(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    manifest = _read_manifest(root)
    if set(manifest) != _EXPECTED_TOP_LEVEL:
        raise VideoSemanticToolchainPinError("toolchain pin field roster drifted")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("pin_id") != "video-semantic-toolchain/2026-08-27-v1"
        or manifest.get("repository") != "ares-matioska/metis"
        or manifest.get("remote_url") != _EXPECTED_REMOTE_URL
        or type(manifest.get("schema_version")) is not int
        or type(manifest.get("retrieval_schema")) is not int
        or type(manifest.get("language_version")) is not str
        or type(manifest.get("revision")) is not str
        or type(manifest.get("tree")) is not str
        or not _OID_RE.fullmatch(manifest.get("revision", ""))
        or not _OID_RE.fullmatch(manifest.get("tree", ""))
        or manifest.get("remote_ref") != "refs/remotes/origin/main"
    ):
        raise VideoSemanticToolchainPinError("toolchain pin identity drifted")
    ancestors = manifest.get("delivery_ancestors")
    if (
        not isinstance(ancestors, Mapping)
        or set(ancestors)
        != {
            "grammar",
            "full_corpus",
            "structured_sync",
            "semantic_retrieval",
        }
        or any(
            not isinstance(value, str) or _OID_RE.fullmatch(value) is None
            for value in ancestors.values()
        )
    ):
        raise VideoSemanticToolchainPinError("delivery ancestor roster drifted")
    runtime = manifest.get("runtime")
    if (
        not isinstance(runtime, Mapping)
        or set(runtime) != {"node_version", "node_sha256", "node_bytes", "node_modules_sha256"}
        or runtime.get("node_version") != "v22.20.0"
        or not isinstance(runtime.get("node_sha256"), str)
        or not isinstance(runtime.get("node_modules_sha256"), str)
        or _SHA256_RE.fullmatch(runtime.get("node_sha256", "")) is None
        or _SHA256_RE.fullmatch(runtime.get("node_modules_sha256", "")) is None
        or type(runtime.get("node_bytes")) is not int
        or not 1 <= runtime["node_bytes"] <= MAX_NODE_BYTES
    ):
        raise VideoSemanticToolchainPinError("toolchain runtime identity drifted")
    dependency = manifest.get("full_corpus_dependency")
    if (
        not isinstance(dependency, Mapping)
        or set(dependency) != {"repository", "revision", "tree", "remote_ref"}
        or dependency.get("repository") != "play-demo"
        or dependency.get("remote_ref") != "refs/remotes/origin/main"
        or not isinstance(dependency.get("revision"), str)
        or not isinstance(dependency.get("tree"), str)
        or _OID_RE.fullmatch(dependency.get("revision", "")) is None
        or _OID_RE.fullmatch(dependency.get("tree", "")) is None
    ):
        raise VideoSemanticToolchainPinError("full-corpus dependency identity drifted")
    evidence = _exact_sequence(manifest.get("evidence"), "evidence")
    if len(evidence) != MAX_EVIDENCE_ITEMS:
        raise VideoSemanticToolchainPinError("evidence roster has an unexpected cardinality")
    observed_ids: set[str] = set()
    observed_paths: set[str] = set()
    observed_oids: set[str] = set()
    for item in evidence:
        if not isinstance(item, Mapping) or set(item) != {"id", "path", "blob_oid", "sha256"}:
            raise VideoSemanticToolchainPinError("evidence entry shape drifted")
        evidence_id = item.get("id")
        if not isinstance(evidence_id, str):
            raise VideoSemanticToolchainPinError("evidence ID is not text")
        path = _safe_relative(item.get("path"), "evidence path")
        blob_oid = item.get("blob_oid")
        sha256 = item.get("sha256")
        if (
            evidence_id not in _EXPECTED_EVIDENCE
            or _EXPECTED_EVIDENCE[evidence_id] != path
            or evidence_id in observed_ids
            or path in observed_paths
            or not isinstance(blob_oid, str)
            or blob_oid in observed_oids
            or _OID_RE.fullmatch(blob_oid) is None
            or not isinstance(sha256, str)
            or _SHA256_RE.fullmatch(sha256) is None
        ):
            raise VideoSemanticToolchainPinError("evidence identity drifted")
        observed_ids.add(str(evidence_id))
        observed_paths.add(path)
        observed_oids.add(blob_oid)
    if observed_ids != set(_EXPECTED_EVIDENCE):
        raise VideoSemanticToolchainPinError("evidence roster is incomplete")
    probes = _exact_sequence(manifest.get("probes"), "probes")
    if len(probes) != MAX_PROBE_ITEMS:
        raise VideoSemanticToolchainPinError("probe roster has an unexpected cardinality")
    probe_ids: set[str] = set()
    for probe in probes:
        if not isinstance(probe, Mapping) or set(probe) != {"id", "argv", "success_marker"}:
            raise VideoSemanticToolchainPinError("probe entry shape drifted")
        probe_id = probe.get("id")
        argv = _exact_sequence(probe.get("argv"), "probe argv")
        if not isinstance(probe_id, str):
            raise VideoSemanticToolchainPinError("probe ID is not text")
        if (
            probe_id not in _EXPECTED_PROBES
            or probe_id in probe_ids
            or not argv
            or argv[0] != "node"
            or len(argv) > MAX_ARGV_ITEMS
            or any(not isinstance(part, str) or not part for part in argv)
            or tuple(argv) != _EXPECTED_PROBE_ARGV[probe_id]
            or probe.get("success_marker") != _EXPECTED_PROBE_MARKERS[probe_id]
        ):
            raise VideoSemanticToolchainPinError("probe identity drifted")
        probe_ids.add(str(probe_id))
    if probe_ids != _EXPECTED_PROBES:
        raise VideoSemanticToolchainPinError("probe roster is incomplete")
    denominators = manifest.get("expected_denominators")
    expected_denominators = {
        "schema2_traced_annotations": 9,
        "schema2_ast_nodes": 27,
        "full_corpus_documents": 411,
        "unexpected_errors": 0,
        "sentinel_collisions": 0,
        "expected_negative_parse_errors": 31,
    }
    if (
        not isinstance(denominators, Mapping)
        or set(denominators) != set(expected_denominators)
        or any(type(denominators[key]) is not int for key in expected_denominators)
        or denominators != expected_denominators
    ):
        raise VideoSemanticToolchainPinError("expected denominator roster drifted")
    policy = manifest.get("policy")
    expected_policy = {
        "git_objects_only": True,
        "schema1_byte_compat_required": True,
        "schema2_test_chain_required": True,
        "archive_execution": True,
        "network_denied": True,
        "external_repository_writes_denied": True,
    }
    if (
        not isinstance(policy, Mapping)
        or set(policy) != set(expected_policy)
        or any(type(policy[key]) is not bool for key in expected_policy)
        or policy != expected_policy
    ):
        raise VideoSemanticToolchainPinError("toolchain policy drifted")
    nonclaims = manifest.get("nonclaims")
    if (
        not isinstance(nonclaims, list)
        or tuple(nonclaims) != _EXPECTED_NONCLAIMS
        or any(not isinstance(item, str) for item in nonclaims)
    ):
        raise VideoSemanticToolchainPinError("toolchain nonclaims drifted")
    return manifest


def validate_video_semantic_toolchain_pin_contract(root: Path = PROJECT_ROOT) -> list[str]:
    try:
        load_video_semantic_toolchain_pin(root)
        return []
    except (OSError, TypeError, ValueError, UnicodeError, RecursionError) as error:
        return [str(error)]


def _verify_repository(repository: Path, revision: str, tree: str, remote_ref: str) -> None:
    if legacy_pin._run_git(repository, "rev-parse", revision) != revision:
        raise VideoSemanticToolchainPinError("pinned revision is unavailable")
    if legacy_pin._run_git(repository, "rev-parse", f"{revision}^{{tree}}") != tree:
        raise VideoSemanticToolchainPinError("pinned tree differs")
    if legacy_pin._run_git(repository, "rev-parse", remote_ref) != revision:
        raise VideoSemanticToolchainPinError("promoted remote-tracking ref differs from pin")


def _verify_evidence(manifest: Mapping[str, Any], repository: Path) -> list[dict[str, str]]:
    verified: list[dict[str, str]] = []
    revision = manifest["revision"]
    for item in manifest["evidence"]:
        row = str(legacy_pin._run_git(repository, "ls-tree", revision, "--", item["path"])).split()
        if row != ["100644", "blob", item["blob_oid"], item["path"]]:
            raise VideoSemanticToolchainPinError("toolchain evidence Git identity drifted")
        raw = legacy_pin._run_git(repository, "cat-file", "blob", item["blob_oid"], text=False)
        assert isinstance(raw, bytes)
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        if digest != item["sha256"]:
            raise VideoSemanticToolchainPinError("toolchain evidence content drifted")
        verified.append({"id": item["id"], "path": item["path"], "sha256": digest})
    package_raw = legacy_pin._run_git(
        repository, "cat-file", "blob", f"{revision}:tooling/package.json", text=False
    )
    assert isinstance(package_raw, bytes)
    package = json.loads(package_raw)
    test_chain = package.get("scripts", {}).get("test")
    if not isinstance(test_chain, str) or any(
        token not in test_chain for token in _REQUIRED_TEST_CHAIN
    ):
        raise VideoSemanticToolchainPinError("semantic gate is absent from the default test chain")
    for ancestor in manifest["delivery_ancestors"].values():
        legacy_pin._run_git(repository, "merge-base", "--is-ancestor", ancestor, revision)
    return verified


def _probe_environment(scratch: Path, home: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "TMPDIR": str(scratch),
        "HOME": str(home),
    }


def _sandbox_policy(snapshot: Path, scratch: Path, play_demo: Path) -> str:
    snapshot = snapshot.resolve(strict=True)
    scratch = scratch.resolve(strict=True)
    play_demo = play_demo.resolve(strict=True)
    home = Path.home().resolve(strict=True)
    return " ".join(
        (
            "(version 1)",
            "(allow default)",
            f"(allow file-write* (subpath {json.dumps(str(scratch))}))",
            f"(allow file-read* (subpath {json.dumps(str(snapshot))}))",
            f"(allow file-read* (subpath {json.dumps(str(play_demo))}))",
            '(allow file-read* (literal "/dev/null"))',
            '(allow file-write* (literal "/dev/null"))',
            "(deny network*)",
            "(deny file-write*)",
            f"(deny file-read* (subpath {json.dumps(str(home))}))",
        )
    )


def _prepare_snapshot(
    manifest: Mapping[str, Any], repository: Path, play_demo: Path, node_bytes: bytes
) -> tuple[tempfile.TemporaryDirectory[str], Path, Path, Path, Path]:
    archive = legacy_pin._run_git(
        repository, "archive", "--format=tar", manifest["revision"], text=False
    )
    assert isinstance(archive, bytes)
    temporary = tempfile.TemporaryDirectory(prefix="metis-model1-video-toolchain-")
    snapshot = Path(temporary.name)
    try:
        legacy_pin._safe_extract_archive(archive, snapshot)
        subprocess.run(
            ["/usr/bin/git", "init", "-q"],
            cwd=snapshot,
            check=True,
            capture_output=True,
            env=legacy_pin._git_process_environment(),
            timeout=30,
        )
        subprocess.run(
            ["/usr/bin/git", "add", "-f", "--", "."],
            cwd=snapshot,
            check=True,
            capture_output=True,
            env=legacy_pin._git_process_environment(),
            timeout=60,
        )
        dependency_archive = legacy_pin._run_git(
            play_demo,
            "archive",
            "--format=tar",
            manifest["full_corpus_dependency"]["revision"],
            text=False,
        )
        assert isinstance(dependency_archive, bytes)
        isolated_home = snapshot / "probe-home"
        isolated_play_demo = isolated_home / "Developer" / "play-demo"
        isolated_play_demo.mkdir(parents=True, mode=0o700)
        legacy_pin._safe_extract_archive(dependency_archive, isolated_play_demo)
        subprocess.run(
            ["/usr/bin/git", "init", "-q"],
            cwd=isolated_play_demo,
            check=True,
            capture_output=True,
            env=legacy_pin._git_process_environment(),
            timeout=30,
        )
        subprocess.run(
            ["/usr/bin/git", "add", "-f", "--", "."],
            cwd=isolated_play_demo,
            check=True,
            capture_output=True,
            env=legacy_pin._git_process_environment(),
            timeout=60,
        )
        tooling = snapshot / "tooling"
        source_modules = (repository / "tooling/node_modules").resolve(strict=True)
        snapshot_modules = tooling / "node_modules"
        shutil.copytree(source_modules, snapshot_modules, symlinks=True)
        if (
            "sha256:" + legacy_pin._node_modules_sha256(snapshot_modules)
            != manifest["runtime"]["node_modules_sha256"]
        ):
            raise VideoSemanticToolchainPinError("copied node_modules differs from pin")
        node = snapshot / "pinned-node"
        node.write_bytes(node_bytes)
        node.chmod(0o500)
        scratch = snapshot / "probe-scratch"
        scratch.mkdir(mode=0o700)
        return temporary, tooling, node, scratch, isolated_home
    except Exception:
        temporary.cleanup()
        raise


def _run_probes(
    manifest: Mapping[str, Any],
    repository: Path,
    play_demo: Path,
    node_bytes: bytes,
) -> list[dict[str, Any]]:
    temporary, tooling, node, scratch, isolated_home = _prepare_snapshot(
        manifest, repository, play_demo, node_bytes
    )
    snapshot = Path(temporary.name)
    try:
        policy = _sandbox_policy(snapshot, scratch, play_demo)
        reports: list[dict[str, Any]] = []
        version_check = subprocess.run(
            [str(legacy_pin.SANDBOX_EXEC), "-p", policy, str(node), "--version"],
            cwd=tooling,
            check=False,
            capture_output=True,
            timeout=10,
            env=_probe_environment(scratch, isolated_home),
        )
        if (
            len(version_check.stdout) > MAX_STDOUT_BYTES
            or len(version_check.stderr) > MAX_STDERR_BYTES
        ):
            raise VideoSemanticToolchainPinError("Node version output exceeds cap")
        if (
            version_check.returncode != 0
            or version_check.stdout.decode("utf-8", errors="strict").strip()
            != manifest["runtime"]["node_version"]
        ):
            raise VideoSemanticToolchainPinError("archived Node version differs from the pin")
        for probe in manifest["probes"]:
            argv = [str(node), *probe["argv"][1:]]
            completed = subprocess.run(
                [str(legacy_pin.SANDBOX_EXEC), "-p", policy, *argv],
                cwd=tooling,
                check=False,
                capture_output=True,
                timeout=PROBE_TIMEOUT_SECONDS,
                env=_probe_environment(scratch, isolated_home),
            )
            if len(completed.stdout) > MAX_STDOUT_BYTES or len(completed.stderr) > MAX_STDERR_BYTES:
                raise VideoSemanticToolchainPinError("semantic probe output exceeds cap")
            try:
                stdout = completed.stdout.decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise VideoSemanticToolchainPinError(
                    "semantic probe output is not UTF-8"
                ) from error
            marker = probe["success_marker"]
            if completed.returncode != 0 or (marker is not None and marker not in stdout):
                raise VideoSemanticToolchainPinError(f"semantic probe failed: {probe['id']}")
            reports.append(
                {
                    "id": probe["id"],
                    "exit_code": completed.returncode,
                    "stdout_sha256": "sha256:" + hashlib.sha256(completed.stdout).hexdigest(),
                    "stderr_sha256": "sha256:" + hashlib.sha256(completed.stderr).hexdigest(),
                }
            )
        return reports
    except (OSError, subprocess.SubprocessError) as error:
        if isinstance(error, VideoSemanticToolchainPinError):
            raise
        raise VideoSemanticToolchainPinError("semantic archive probe execution failed") from error
    finally:
        temporary.cleanup()


def verify_video_semantic_toolchain_pin(
    metis_root: Path,
    node_path: Path,
    play_demo_root: Path,
    *,
    execute_probes: bool = True,
) -> dict[str, Any]:
    """Verify the promoted Git objects and, optionally, the archived gate roster."""

    manifest = load_video_semantic_toolchain_pin()
    metis = Path(metis_root).resolve(strict=True)
    play_demo = Path(play_demo_root).resolve(strict=True)
    _verify_repository(metis, manifest["revision"], manifest["tree"], manifest["remote_ref"])
    if legacy_pin._run_git(metis, "config", "--get", "remote.origin.url") != manifest["remote_url"]:
        raise VideoSemanticToolchainPinError("upstream remote identity differs from pin")
    dependency = manifest["full_corpus_dependency"]
    _verify_repository(
        play_demo, dependency["revision"], dependency["tree"], dependency["remote_ref"]
    )
    evidence = _verify_evidence(manifest, metis)
    try:
        node_bytes = legacy_pin._verify_node(Path(node_path), manifest["runtime"])
    except legacy_pin.CatalogMaintenancePinError as error:
        raise VideoSemanticToolchainPinError("successor Node verification failed") from error
    source_modules = (metis / "tooling/node_modules").resolve(strict=True)
    if (
        "sha256:" + legacy_pin._node_modules_sha256(source_modules)
        != manifest["runtime"]["node_modules_sha256"]
    ):
        raise VideoSemanticToolchainPinError("upstream node_modules differs from pin")
    probe_reports = _run_probes(manifest, metis, play_demo, node_bytes) if execute_probes else []
    if execute_probes and len(probe_reports) != len(manifest["probes"]):
        raise VideoSemanticToolchainPinError("semantic probe roster is incomplete")
    _verify_repository(metis, manifest["revision"], manifest["tree"], manifest["remote_ref"])
    _verify_repository(
        play_demo, dependency["revision"], dependency["tree"], dependency["remote_ref"]
    )
    return {
        "schema_version": 1,
        "status": "VERIFIED",
        "pin_id": manifest["pin_id"],
        "revision": manifest["revision"],
        "tree": manifest["tree"],
        "retrieval_schema": 2,
        "evidence_in": len(manifest["evidence"]),
        "evidence_out": len(evidence),
        "evidence_distinct": len({row["id"] for row in evidence}),
        "evidence_gaps": len(manifest["evidence"]) - len(evidence),
        "probes_in": len(manifest["probes"]),
        "probes_out": len(probe_reports),
        "probes_distinct": len({row["id"] for row in probe_reports}),
        "probes_gaps": 0 if execute_probes else len(manifest["probes"]),
        "probes_executed": execute_probes,
        "manifest_sha256": manifest_sha256(manifest),
        "expected_denominators": manifest["expected_denominators"],
        "probe_reports": probe_reports,
        "nonclaims": manifest["nonclaims"],
    }


__all__ = [
    "MANIFEST_PATH",
    "VideoSemanticToolchainPinError",
    "load_video_semantic_toolchain_pin",
    "manifest_sha256",
    "validate_video_semantic_toolchain_pin_contract",
    "verify_video_semantic_toolchain_pin",
]
