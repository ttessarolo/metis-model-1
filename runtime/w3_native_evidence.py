#!/usr/bin/env python3
"""Deterministic metadata-only native-loader closure and parity receipt tooling."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import posixpath
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from metis_model1 import oracles  # noqa: E402

METIS_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
METIS_TREE = "75473e26deff4084a0eb077a4c3e27d52dc07998"
SOURCE_ENTRIES = (
    "tooling/src/compiler/compile.ts",
    "tooling/src/compiler/serialize.ts",
    "tooling/src/language/metis-module.ts",
)
PARSER_PATH = "tooling/node_modules/typescript/lib/typescript.js"
EVIDENCE_PATH = PROJECT_ROOT / "manifests/w3-native-loader-evidence.json"
SCHEMA_PATH = PROJECT_ROOT / "schemas/w3-native-loader-evidence.schema.json"
CENSUS_PATH = PROJECT_ROOT / "runtime/metis_oracle/native_evidence_census.mjs"
LOADER_PATH = PROJECT_ROOT / "runtime/metis_oracle/native_ts_loader.mjs"
RUNNER_PATH = PROJECT_ROOT / "runtime/metis_oracle/runner.ts"
CANDIDATES_PATH = PROJECT_ROOT / "manifests/w3-f1-f3-smoke-candidates.json"
REGISTRY_PATH = PROJECT_ROOT / "manifests/w3-f1-f3-smoke-semantic-specs.json"
DEFAULT_METIS_ROOT = Path("/Users/tommasotessarolo/Developer/ares-matioska/metis")
ROLE_FIELDS = (
    ("F-1", "author", "target_source"),
    ("F-2", "before", "before_source"),
    ("F-2", "after", "after_source"),
    ("F-3", "mutated", "mutated_source"),
    ("F-3", "fixed", "fixed_source"),
)
NON_CLAIMS = [
    "executed_preimage_authority=false",
    "no-durable-parity-evidence",
    "no-production-evidence",
    "no-dataset-qualification",
    "no-training-readiness",
    "no-semantic-accuracy-evidence",
]
REFERENCE_TEMP_MAX_DIRECTORIES = 64
REFERENCE_TEMP_MAX_FILES = 4096
REFERENCE_TEMP_MAX_BYTES = 64 * 1024 * 1024
REFERENCE_TEMP_MAX_FILE_BYTES = 8 * 1024 * 1024
REFERENCE_TEMP_MAX_DEPTH = 16
REFERENCE_POLICY_TEMPLATE = """(version 1)
(deny default)
(deny network*)
(allow file-read*)
(allow process*)
(allow file-write* (subpath (param \"PROCESS_ROOT\")))
(allow sysctl-read)
(allow mach-lookup)
"""


class EvidenceError(ValueError):
    """Raised when reference evidence cannot be reproduced exactly."""


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
        raise EvidenceError("evidence contains non-canonical JSON") from error


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _hash(value: Any) -> str:
    return _hash_bytes(_canonical(value))


def _read_regular(path: Path, label: str) -> bytes:
    try:
        before = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(before.st_mode):
            raise EvidenceError(f"{label} is not a regular file")
        raw = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise EvidenceError(f"{label} is unavailable") from error
    identity = lambda item: (  # noqa: E731
        item.st_dev,
        item.st_ino,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
        item.st_mode,
    )
    if identity(before) != identity(after) or len(raw) != before.st_size:
        raise EvidenceError(f"{label} changed while read")
    return raw


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    input_bytes: bytes | None = None,
    env: dict[str, str] | None = None,
) -> bytes:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            input=input_bytes,
            capture_output=True,
            env=env,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise EvidenceError(f"command could not run: {command[0]}") from error
    if completed.returncode != 0:
        reason = completed.stderr.decode("utf-8", "replace")[:500]
        raise EvidenceError(f"command failed ({completed.returncode}): {reason}")
    return completed.stdout


def _git(metis_root: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    return _run(["git", "-C", str(metis_root), *arguments], input_bytes=input_bytes)


def _git_file(metis_root: Path, path: str) -> bytes:
    return _git(metis_root, "cat-file", "blob", f"{METIS_REVISION}:{path}")


def _git_tree_rows(metis_root: Path, prefix: str) -> dict[str, dict[str, Any]]:
    raw = _git(metis_root, "ls-tree", "-r", "-z", "--long", METIS_REVISION, "--", prefix)
    rows: dict[str, dict[str, Any]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, oid, raw_size = metadata.decode("ascii").split()
            path = raw_path.decode("utf-8")
            size = int(raw_size)
        except (ValueError, UnicodeDecodeError) as error:
            raise EvidenceError("pinned Git tree output is malformed") from error
        if kind != "blob" or path in rows:
            raise EvidenceError("pinned Git tree contains a non-blob or duplicate")
        rows[path] = {"git_blob_oid": oid, "git_mode": mode, "size": size}
    return rows


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise EvidenceError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tooling_pins(metis_root: Path = DEFAULT_METIS_ROOT) -> dict[str, Any]:
    qualifier = _load_module(PROJECT_ROOT / "runtime/w3_qualifier.py", "l66_evidence_qualifier")
    combined = _hash_bytes(
        qualifier.V3_OUTER_SANDBOX_POLICY_TEMPLATE.encode("utf-8")
        + b"\0"
        + qualifier.V3_NODE_SANDBOX_POLICY_TEMPLATE.encode("utf-8")
    )
    if combined != qualifier.V3_OUTER_SANDBOX_POLICY_TEMPLATE_SHA256:
        raise EvidenceError("combined launcher policy recomputation drifted")
    node_path, _ = oracles._resolve_pinned_node()
    node_raw = _read_regular(node_path, "registered Node")
    generator_raw = _read_regular(Path(__file__).resolve(), "evidence generator")
    census_raw = _read_regular(CENSUS_PATH, "AST/trace census")
    loader_raw = _read_regular(LOADER_PATH, "native loader")
    runner_raw = _read_regular(RUNNER_PATH, "runner")
    node_modules = metis_root / "tooling/node_modules"
    if oracles._node_modules_sha256(node_modules) != oracles.PINNED_NODE_MODULES_SHA256:
        raise EvidenceError("registered comparator node_modules drifted")
    comparator_loader = node_modules / "tsx/dist/loader.mjs"
    comparator_raw = _read_regular(comparator_loader, "registered TSX comparator")
    try:
        comparator_manifest = json.loads(
            _read_regular(node_modules / "tsx/package.json", "TSX package manifest")
        )
    except json.JSONDecodeError as error:
        raise EvidenceError("TSX package manifest is malformed") from error
    if comparator_manifest.get("name") != "tsx" or not isinstance(
        comparator_manifest.get("version"), str
    ):
        raise EvidenceError("TSX comparator identity drifted")
    if _hash_bytes(node_raw) != "sha256:" + oracles.PINNED_NODE_BINARY_SHA256:
        raise EvidenceError("registered Node drifted")
    if _hash_bytes(loader_raw) != "sha256:" + oracles.PINNED_LOADER_SHA256:
        raise EvidenceError("registered loader drifted")
    if _hash_bytes(runner_raw) != "sha256:" + oracles.PINNED_RUNNER_SHA256:
        raise EvidenceError("registered runner drifted")
    return {
        "census": {
            "path": "runtime/metis_oracle/native_evidence_census.mjs",
            "sha256": _hash_bytes(census_raw),
        },
        "generator": {
            "path": "runtime/w3_native_evidence.py",
            "sha256": _hash_bytes(generator_raw),
        },
        "loader": {
            "mode": 0o444,
            "path": ".metis-oracle/native_ts_loader.mjs",
            "sha256": _hash_bytes(loader_raw),
        },
        "node": {
            "retained_mode": 0o555,
            "sha256": _hash_bytes(node_raw),
            "size": len(node_raw),
            "source_mode": stat.S_IMODE(node_path.lstat().st_mode),
            "version": oracles.PINNED_NODE_VERSION,
        },
        "policies": {
            "combined_sha256": combined,
            "native_execution_sha256": _hash_bytes(
                oracles.CAPSULE_EXECUTION_POLICY_TEMPLATE.encode("utf-8")
            ),
            "node_sha256": qualifier.V3_NODE_SANDBOX_POLICY_TEMPLATE_SHA256,
            "oracle_sha256": "sha256:" + oracles.SANDBOX_POLICY_SHA256,
            "outer_sha256": _hash_bytes(qualifier.V3_OUTER_SANDBOX_POLICY_TEMPLATE.encode("utf-8")),
            "reference_comparator_sha256": _hash_bytes(REFERENCE_POLICY_TEMPLATE.encode("utf-8")),
        },
        "reference_comparator": {
            "allows_child_process": True,
            "allows_temp_writes": True,
            "credit": "reference-only-no-production-authority",
            "node_modules_sha256": "sha256:" + oracles.PINNED_NODE_MODULES_SHA256,
            "package": f"tsx@{comparator_manifest['version']}",
            "path": "tooling/node_modules/tsx/dist/loader.mjs",
            "sha256": _hash_bytes(comparator_raw),
        },
        "runner": {
            "mode": 0o444,
            "path": ".metis-oracle/runner.ts",
            "sha256": _hash_bytes(runner_raw),
        },
    }


def _skip_typescript_space_and_comments(source: str, offset: int) -> int:
    while offset < len(source):
        if source[offset].isspace():
            offset += 1
        elif source.startswith("//", offset):
            newline = source.find("\n", offset + 2)
            offset = len(source) if newline < 0 else newline + 1
        elif source.startswith("/*", offset):
            end = source.find("*/", offset + 2)
            if end < 0:
                raise EvidenceError("TypeScript source contains an unterminated comment")
            offset = end + 2
        else:
            break
    return offset


def _typescript_import_statement_end(source: str, offset: int) -> int:
    quote: str | None = None
    comment: str | None = None
    depth = 0
    while offset < len(source):
        if quote is not None:
            if source[offset] == "\\":
                offset += 2
                continue
            if source[offset] == quote:
                quote = None
            offset += 1
            continue
        if comment == "line":
            if source[offset] == "\n":
                comment = None
            offset += 1
            continue
        if comment == "block":
            if source.startswith("*/", offset):
                comment = None
                offset += 2
            else:
                offset += 1
            continue
        if source.startswith("//", offset):
            comment = "line"
            offset += 2
            continue
        if source.startswith("/*", offset):
            comment = "block"
            offset += 2
            continue
        character = source[offset]
        if character in {'"', "'"}:
            quote = character
        elif character in "({[":
            depth += 1
        elif character in ")}]":
            depth -= 1
            if depth < 0:
                raise EvidenceError("TypeScript import delimiters are malformed")
        elif character == ";" and depth == 0:
            return offset + 1
        offset += 1
    raise EvidenceError("TypeScript import is not terminated by a semicolon")


def _strip_typescript_comments(statement: str) -> str:
    rendered: list[str] = []
    offset = 0
    quote: str | None = None
    while offset < len(statement):
        if quote is not None:
            rendered.append(statement[offset])
            if statement[offset] == "\\" and offset + 1 < len(statement):
                rendered.append(statement[offset + 1])
                offset += 2
                continue
            if statement[offset] == quote:
                quote = None
            offset += 1
            continue
        if statement[offset] in {'"', "'"}:
            quote = statement[offset]
            rendered.append(statement[offset])
            offset += 1
            continue
        if statement.startswith("//", offset):
            newline = statement.find("\n", offset + 2)
            rendered.append(" ")
            offset = len(statement) if newline < 0 else newline + 1
            continue
        if statement.startswith("/*", offset):
            end = statement.find("*/", offset + 2)
            if end < 0:
                raise EvidenceError("TypeScript import contains an unterminated comment")
            rendered.append(" ")
            offset = end + 2
            continue
        rendered.append(statement[offset])
        offset += 1
    if quote is not None:
        raise EvidenceError("TypeScript import contains an unterminated string")
    return "".join(rendered)


def _resolve_typescript_import(path: str, specifier: str, available: set[str]) -> str | None:
    if not specifier or "\\" in specifier or any(ord(character) < 0x20 for character in specifier):
        raise EvidenceError("TypeScript import specifier is invalid")
    if not specifier.startswith("."):
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(path), specifier))
    candidates: list[str]
    if base.endswith((".js", ".mjs", ".cjs")):
        stem = base.rsplit(".", 1)[0]
        candidates = [f"{stem}{suffix}" for suffix in (".ts", ".mts", ".cts", ".tsx")]
    elif base.endswith((".ts", ".mts", ".cts", ".tsx")):
        candidates = [base]
    else:
        candidates = [f"{base}{suffix}" for suffix in (".ts", ".mts", ".cts", ".tsx")]
        candidates.extend(
            posixpath.join(base, f"index{suffix}") for suffix in (".ts", ".mts", ".cts", ".tsx")
        )
    matches = [candidate for candidate in candidates if candidate in available]
    if len(matches) != 1:
        raise EvidenceError(f"relative TypeScript import from {path} is ambiguous or missing")
    return matches[0]


def _parse_typescript_imports(
    path: str,
    raw_source: bytes,
    available: set[str],
) -> list[dict[str, Any]]:
    try:
        source = raw_source.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceError(f"TypeScript source {path} is not UTF-8") from error
    offset = _skip_typescript_space_and_comments(source, 0)
    imports: list[dict[str, Any]] = []
    while source.startswith("import", offset) and (
        offset + len("import") == len(source)
        or not (source[offset + len("import")].isalnum() or source[offset + len("import")] in "_$")
    ):
        end = _typescript_import_statement_end(source, offset)
        statement = _strip_typescript_comments(source[offset:end])
        offset = _skip_typescript_space_and_comments(source, end)
        side_effect = re.fullmatch(
            r"\s*import\s*(['\"])([^'\"]+)\1\s*;\s*",
            statement,
            flags=re.DOTALL,
        )
        type_only = False
        if side_effect is not None:
            specifier = side_effect.group(2)
        else:
            import_equals = re.fullmatch(
                r"\s*import\s+(type\s+)?[A-Za-z_$][A-Za-z0-9_$]*\s*=\s*"
                r"require\(\s*(['\"])([^'\"]+)\2\s*\)\s*;\s*",
                statement,
                flags=re.DOTALL,
            )
            if import_equals is not None:
                type_only = import_equals.group(1) is not None
                specifier = import_equals.group(3)
            else:
                from_match = re.search(
                    r"\bfrom\s*(['\"])([^'\"]+)\1\s*;\s*$",
                    statement,
                    flags=re.DOTALL,
                )
                if from_match is None:
                    raise EvidenceError(
                        f"TypeScript import in {path} is outside the static profile"
                    )
                specifier = from_match.group(2)
                clause = statement[len("import") : from_match.start()].strip()
                type_only = re.match(r"^type\b", clause) is not None
                if not type_only:
                    left_brace = clause.find("{")
                    right_brace = clause.rfind("}")
                    if left_brace >= 0 and right_brace > left_brace:
                        elements = [
                            element.strip()
                            for element in clause[left_brace + 1 : right_brace].split(",")
                            if element.strip()
                        ]
                        type_only = bool(elements) and all(
                            re.match(r"^type\b", element) is not None for element in elements
                        )
        imports.append(
            {
                "dynamic": False,
                "resolved_path": _resolve_typescript_import(path, specifier, available),
                "specifier": specifier,
                "type_only": type_only,
            }
        )
    raw_declaration_count = len(re.findall(r"(?m)^[ \t]*import\b", source))
    if raw_declaration_count != len(imports):
        raise EvidenceError(f"TypeScript imports in {path} are not one leading static block")
    if re.search(r"\bimport\s*\(", source):
        raise EvidenceError(f"TypeScript source {path} contains a dynamic import")
    if re.search(
        r"(?ms)^[ \t]*export(?:[ \t]+type)?[ \t]+(?:\*|\{).*?"
        r"\bfrom[ \t\r\n]*['\"]",
        source,
    ):
        raise EvidenceError(f"TypeScript source {path} contains a re-export")
    imports.sort(key=_canonical)
    return imports


def _ast_census(metis_root: Path) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    try:
        actual_tree = (
            _git(metis_root, "rev-parse", f"{METIS_REVISION}^{{tree}}").decode("ascii").strip()
        )
    except UnicodeDecodeError as error:
        raise EvidenceError("pinned Git tree identity is malformed") from error
    if actual_tree != METIS_TREE:
        raise EvidenceError("pinned Git revision does not resolve to the registered tree")
    tree = _git_tree_rows(metis_root, "tooling/src")
    source_bytes = {
        path: _git_file(metis_root, path)
        for path in sorted(tree)
        if path.endswith((".ts", ".mts", ".cts", ".tsx"))
    }
    if not set(SOURCE_ENTRIES) <= source_bytes.keys():
        raise EvidenceError("source closure entry is absent from the pinned Git tree")
    available = set(source_bytes)
    queue = sorted(SOURCE_ENTRIES)
    visited: set[str] = set()
    imports_by_path: dict[str, list[dict[str, Any]]] = {}
    while queue:
        path = queue.pop(0)
        if path in visited:
            continue
        visited.add(path)
        imports = _parse_typescript_imports(path, source_bytes[path], available)
        imports_by_path[path] = imports
        for item in imports:
            resolved = item["resolved_path"]
            if resolved is not None and resolved not in visited:
                queue.append(resolved)
        queue.sort()
    selected: list[dict[str, Any]] = []
    selected_bytes: dict[str, bytes] = {}
    for path in sorted(visited):
        raw_source = source_bytes[path]
        if len(raw_source) != tree[path]["size"]:
            raise EvidenceError("pinned Git blob size drifted")
        git_blob_oid = hashlib.sha1(  # noqa: S324 - Git object identity is SHA-1 by format.
            f"blob {len(raw_source)}\0".encode("ascii") + raw_source
        ).hexdigest()
        if git_blob_oid != tree[path]["git_blob_oid"]:
            raise EvidenceError("pinned Git blob object identity drifted")
        selected.append(
            {
                "git_blob_oid": tree[path]["git_blob_oid"],
                "imports": imports_by_path[path],
                "mode": 0o444,
                "path": path,
                "sha256": _hash_bytes(raw_source),
                "size": len(raw_source),
            }
        )
        selected_bytes[path] = raw_source
    if len(selected) != 32 or sum(row["size"] for row in selected) != 967_481:
        raise EvidenceError("source AST fixed point denominator drifted")
    if sum(len(row["imports"]) for row in selected) != 99:
        raise EvidenceError("source AST edge denominator drifted")
    if sum(edge["resolved_path"] is not None for row in selected for edge in row["imports"]) != 66:
        raise EvidenceError("source relative-resolution denominator drifted")
    return selected, selected_bytes


def _package_closure(
    metis_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, bytes], list[str]]:
    modules = metis_root / "tooling/node_modules"
    packages: set[str] = set()
    queue = ["langium"]
    identities: dict[str, str] = {}
    while queue:
        package = queue.pop()
        if package in packages:
            continue
        package_root = modules / package
        raw_manifest = _read_regular(package_root / "package.json", f"package {package}")
        try:
            manifest = json.loads(raw_manifest)
        except json.JSONDecodeError as error:
            raise EvidenceError(f"package {package} manifest is malformed") from error
        if manifest.get("name") != package or not isinstance(manifest.get("version"), str):
            raise EvidenceError(f"package {package} identity drifted")
        packages.add(package)
        identities[package] = f"{package}@{manifest['version']}"
        dependencies = manifest.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise EvidenceError(f"package {package} dependencies are malformed")
        queue.extend(sorted(dependencies))
    rows: list[dict[str, Any]] = []
    package_bytes: dict[str, bytes] = {}
    for package in sorted(packages):
        package_root = modules / package
        for path in sorted(package_root.rglob("*"), key=lambda item: item.as_posix().encode()):
            if path.is_symlink():
                raise EvidenceError("registered package closure contains a symlink")
            if not path.is_file():
                continue
            relative = f"tooling/node_modules/{package}/{path.relative_to(package_root).as_posix()}"
            raw = _read_regular(path, f"package file {relative}")
            rows.append(
                {
                    "mode": 0o444,
                    "package": identities[package],
                    "path": relative,
                    "sha256": _hash_bytes(raw),
                    "size": len(raw),
                }
            )
            package_bytes[relative] = raw
    rows.sort(key=lambda row: row["path"].encode())
    if len(packages) != 15 or len(rows) != 1_790 or sum(row["size"] for row in rows) != 7_710_543:
        raise EvidenceError("registered package closure denominator drifted")
    return rows, package_bytes, sorted(identities.values())


def _identity_bytes(execution_policy_sha256: str) -> bytes:
    return _canonical(
        {
            "execution_policy_sha256": execution_policy_sha256.removeprefix("sha256:"),
            "loader_flags": list(oracles.LOADER_FLAGS),
            "loader_sha256": oracles.PINNED_LOADER_SHA256,
            "lock_sha256": oracles.PINNED_TOOLING_LOCK_SHA256,
            "node_binary_sha256": oracles.PINNED_NODE_BINARY_SHA256,
            "node_modules_sha256": oracles.PINNED_NODE_MODULES_SHA256,
            "oracle_policy_sha256": oracles.SANDBOX_POLICY_SHA256,
            "oracle_policy_version": oracles.SANDBOX_POLICY_VERSION,
            "package_sha256": oracles.PINNED_TOOLING_PACKAGE_SHA256,
            "revision": METIS_REVISION,
            "runner_sha256": oracles.PINNED_RUNNER_SHA256,
            "sandbox_exec_path": oracles.SANDBOX_EXEC_IDENTITY,
            "tree": METIS_TREE,
        }
    )


def _control_bytes(metis_root: Path, execution_policy_sha256: str) -> dict[str, bytes]:
    return {
        ".metis-oracle-identity.json": _identity_bytes(execution_policy_sha256),
        ".metis-oracle/native_ts_loader.mjs": _read_regular(LOADER_PATH, "native loader"),
        ".metis-oracle/runner.ts": _read_regular(RUNNER_PATH, "runner"),
        "tooling/package-lock.json": _git_file(metis_root, "tooling/package-lock.json"),
        "tooling/package.json": _git_file(metis_root, "tooling/package.json"),
    }


def _materialize(root: Path, files: dict[str, bytes]) -> None:
    root.mkdir(mode=0o700)
    directories = {PurePosixPath(path).parent for path in files}
    expanded: set[PurePosixPath] = set()
    for directory in directories:
        cursor = directory
        while cursor != PurePosixPath("."):
            expanded.add(cursor)
            cursor = cursor.parent
    for directory in sorted(expanded, key=lambda item: (len(item.parts), item.as_posix())):
        (root / directory.as_posix()).mkdir(mode=0o700, exist_ok=True)
    for path, raw in files.items():
        target = root / path
        target.write_bytes(raw)
        target.chmod(0o444)
    for directory in sorted(expanded, key=lambda item: len(item.parts), reverse=True):
        (root / directory.as_posix()).chmod(0o555)
    root.chmod(0o555)


def _runner_arguments(
    *,
    capsule: Path,
    loader: Path,
    runner: Path,
    node: Path,
    execution_policy_sha256: str,
) -> list[str]:
    runtime = oracles._runtime_identity_policy(
        METIS_REVISION,
        METIS_TREE,
        execution_policy_sha256=execution_policy_sha256,
    )
    return [
        "--metis-root",
        str(capsule),
        "--metis-revision",
        METIS_REVISION,
        "--metis-tree",
        METIS_TREE,
        "--loader-path",
        str(loader),
        "--loader-sha256",
        oracles.PINNED_LOADER_SHA256,
        "--runtime-node-path",
        runtime["node_path"],
        "--node-actual-path",
        str(node),
        "--runtime-loader-path",
        runtime["loader_path"],
        "--runtime-loader-flags",
        json.dumps(list(oracles.LOADER_FLAGS), separators=(",", ":")),
        "--runtime-runner-path",
        runtime["runner_path"],
        "--runner-actual-path",
        str(runner),
        "--snapshot-identity",
        f"snapshot://{METIS_REVISION}/{METIS_TREE}",
        "--node-modules-sha256",
        oracles.PINNED_NODE_MODULES_SHA256,
        "--runner-sha256",
        oracles.PINNED_RUNNER_SHA256,
        "--node-binary-sha256",
        oracles.PINNED_NODE_BINARY_SHA256,
        "--oracle-policy-version",
        oracles.SANDBOX_POLICY_VERSION,
        "--oracle-policy-sha256",
        oracles.SANDBOX_POLICY_SHA256,
        "--execution-policy-sha256",
        execution_policy_sha256.removeprefix("sha256:"),
        "--tooling-package-sha256",
        oracles.PINNED_TOOLING_PACKAGE_SHA256,
        "--tooling-lock-sha256",
        oracles.PINNED_TOOLING_LOCK_SHA256,
    ]


def _bootstrap(runner: Path, loader: Path, arguments: list[str]) -> str:
    return (
        f"process.execArgv={json.dumps([*oracles.LOADER_FLAGS, str(loader)])};"
        f"process.argv={json.dumps(['node', str(runner), *arguments])};"
        f"await import({json.dumps(runner.as_uri())});"
    )


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=3)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, 0)
        raise EvidenceError("reference parity left a residual process group")


def _validate_reference_temp_receipt(value: dict[str, Any]) -> None:
    rows = value["rows"]
    paths = [row["path"] for row in rows]
    if paths != sorted(paths, key=str.encode) or len(paths) != len(set(paths)):
        raise EvidenceError("TSX reference temp roster is not exact and ordered")
    files = [row for row in rows if row["kind"] == "file"]
    directories = [row for row in rows if row["kind"] == "directory"]
    for row in rows:
        path = PurePosixPath(row["path"])
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or len(path.parts) > REFERENCE_TEMP_MAX_DEPTH
        ):
            raise EvidenceError("TSX reference temp roster contains an unsafe path")
        if row["kind"] == "directory":
            if set(row) != {"kind", "mode", "path", "size"} or row["size"] != 0:
                raise EvidenceError("TSX reference temp directory row is malformed")
        elif row["kind"] == "file":
            if set(row) != {"kind", "mode", "path", "sha256", "size"}:
                raise EvidenceError("TSX reference temp file row is malformed")
        else:
            raise EvidenceError("TSX reference temp roster contains a special file")
    total_bytes = sum(row["size"] for row in files)
    if (
        value["reference_only"] is not True
        or value["directories"] != len(directories)
        or value["files"] != len(files)
        or value["bytes"] != total_bytes
        or value["roster_sha256"] != _hash(rows)
        or len(directories) > REFERENCE_TEMP_MAX_DIRECTORIES
        or len(files) > REFERENCE_TEMP_MAX_FILES
        or total_bytes > REFERENCE_TEMP_MAX_BYTES
        or any(row["size"] > REFERENCE_TEMP_MAX_FILE_BYTES for row in files)
    ):
        raise EvidenceError("TSX reference temp receipt exceeds its bounds or hash")


def _snapshot_reference_temp(root: Path) -> dict[str, Any]:
    try:
        root_before = root.lstat()
        resolved_root = root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise EvidenceError("TSX reference temp root is unavailable") from error
    if root.is_symlink() or not stat.S_ISDIR(root_before.st_mode) or resolved_root != root:
        raise EvidenceError("TSX reference temp root is not a canonical directory")
    rows: list[dict[str, Any]] = []

    def visit(directory: Path, prefix: PurePosixPath) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.encode())
        except OSError as error:
            raise EvidenceError("TSX reference temp roster cannot be enumerated") from error
        for entry in entries:
            relative = prefix / entry.name
            if entry.name in {"", ".", ".."} or "/" in entry.name:
                raise EvidenceError("TSX reference temp roster contains an unsafe name")
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise EvidenceError("TSX reference temp entry is unavailable") from error
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISLNK(metadata.st_mode):
                raise EvidenceError("TSX reference temp roster contains a symlink")
            if stat.S_ISDIR(metadata.st_mode):
                rows.append(
                    {
                        "kind": "directory",
                        "mode": mode,
                        "path": relative.as_posix(),
                        "size": 0,
                    }
                )
                visit(Path(entry.path), relative)
            elif stat.S_ISREG(metadata.st_mode):
                raw = _read_regular(Path(entry.path), "TSX reference temp file")
                if len(raw) != metadata.st_size:
                    raise EvidenceError("TSX reference temp file size drifted")
                rows.append(
                    {
                        "kind": "file",
                        "mode": mode,
                        "path": relative.as_posix(),
                        "sha256": _hash_bytes(raw),
                        "size": len(raw),
                    }
                )
            else:
                raise EvidenceError("TSX reference temp roster contains a special file")
            if len(rows) > REFERENCE_TEMP_MAX_DIRECTORIES + REFERENCE_TEMP_MAX_FILES:
                raise EvidenceError("TSX reference temp roster exceeds its entry cap")

    visit(root, PurePosixPath())
    rows.sort(key=lambda row: row["path"].encode())
    files = [row for row in rows if row["kind"] == "file"]
    receipt = {
        "bytes": sum(row["size"] for row in files),
        "directories": sum(row["kind"] == "directory" for row in rows),
        "files": len(files),
        "reference_only": True,
        "roster_sha256": _hash(rows),
        "rows": rows,
    }
    _validate_reference_temp_receipt(receipt)
    return receipt


def _cleanup_reference_temp(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    _validate_reference_temp_receipt(receipt)
    if _canonical(_snapshot_reference_temp(root)) != _canonical(receipt):
        raise EvidenceError("TSX reference temp roster changed before cleanup")
    rows = receipt["rows"]
    for row in sorted(
        (item for item in rows if item["kind"] == "file"),
        key=lambda item: (len(PurePosixPath(item["path"]).parts), item["path"]),
        reverse=True,
    ):
        target = root / row["path"]
        try:
            metadata = target.lstat()
            if target.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                raise EvidenceError("TSX reference temp file changed before cleanup")
            target.unlink()
        except OSError as error:
            raise EvidenceError("TSX reference temp file cleanup failed") from error
    for row in sorted(
        (item for item in rows if item["kind"] == "directory"),
        key=lambda item: (len(PurePosixPath(item["path"]).parts), item["path"]),
        reverse=True,
    ):
        target = root / row["path"]
        try:
            metadata = target.lstat()
            if target.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
                raise EvidenceError("TSX reference temp directory changed before cleanup")
            target.rmdir()
        except OSError as error:
            raise EvidenceError("TSX reference temp directory cleanup failed") from error
    residual = _snapshot_reference_temp(root)
    if residual["rows"]:
        raise EvidenceError("TSX reference temp cleanup left residual entries")
    return {
        "attempted": True,
        "deleted_directories": receipt["directories"],
        "deleted_files": receipt["files"],
        "residual_entries": 0,
    }


def _invoke(
    *,
    command: list[str],
    policy: str,
    process_root: Path,
    cwd: Path,
    request: dict[str, Any],
    env: dict[str, str],
    pass_fds: tuple[int, ...] = (),
) -> dict[str, Any]:
    stdout_path = process_root / "stdout.json"
    stderr_path = process_root / "stderr.txt"
    stdout = stdout_path.open("wb")
    stderr = stderr_path.open("wb")
    supervised = [
        str(oracles.SANDBOX_EXEC_PATH),
        "-p",
        policy,
        "-D",
        f"PROCESS_ROOT={process_root}",
        *command,
    ]
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            supervised,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            env=env,
            pass_fds=pass_fds,
            start_new_session=True,
        )
        try:
            process.communicate(input=_canonical(request), timeout=60)
        except subprocess.TimeoutExpired as error:
            raise EvidenceError("reference parity runner timed out") from error
    finally:
        stdout.close()
        stderr.close()
        if process is not None:
            _kill_group(process)
    if process is None or process.returncode != 0:
        reason = stderr_path.read_text(encoding="utf-8", errors="replace")[:500]
        raise EvidenceError(f"reference parity runner failed: {reason}")
    raw_stderr = stderr_path.read_bytes()
    try:
        result = json.loads(stdout_path.read_bytes())
    except json.JSONDecodeError as error:
        raise EvidenceError("reference parity output is malformed") from error
    if stdout_path.read_bytes() != _canonical(result):
        raise EvidenceError("reference parity output is not canonical")
    result["__stderr_bytes"] = len(raw_stderr)
    return result


def _native_policy(
    capsule: Path,
    runtime_root: Path,
    node: Path,
) -> tuple[str, list[str]]:
    ancestor_arguments = [
        argument
        for name, value in oracles._capsule_ancestor_definitions(capsule).items()
        for argument in ("-D", f"{name}={value}")
    ]
    runtime_arguments = [
        argument
        for name, value in oracles._runtime_ancestor_definitions(runtime_root).items()
        for argument in ("-D", f"{name}={value}")
    ]
    definitions = [
        "-D",
        f"NODE_EXECUTABLE={node}",
        "-D",
        f"RUNTIME_ROOT={runtime_root}",
        "-D",
        f"CAPSULE_ROOT={capsule}",
        *ancestor_arguments,
        *runtime_arguments,
    ]
    return oracles.CAPSULE_EXECUTION_POLICY_TEMPLATE, definitions


def _invoke_native(
    *,
    capsule: Path,
    runtime_root: Path,
    node: Path,
    process_root: Path,
    request: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    loader = capsule / ".metis-oracle/native_ts_loader.mjs"
    runner = capsule / ".metis-oracle/runner.ts"
    trace_path = process_root / "trace.jsonl"
    trace_fd = os.open(trace_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    arguments = _runner_arguments(
        capsule=capsule,
        loader=loader,
        runner=runner,
        node=node,
        execution_policy_sha256=oracles.CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"],
    )
    command = [
        str(node),
        "--disable-warning=ExperimentalWarning",
        "--experimental-loader",
        str(loader),
        "--input-type=module",
        "--eval",
        _bootstrap(runner, loader, arguments),
    ]
    policy, definitions = _native_policy(capsule, runtime_root, node)
    env = {
        "LANG": "C",
        "LC_ALL": "C",
        oracles.NATIVE_TRACE_FD_ENV: str(trace_fd),
        "PATH": "",
    }
    try:
        result = _invoke(
            command=[*definitions, *command],
            policy=policy,
            process_root=process_root,
            cwd=capsule / "tooling",
            request=request,
            env=env,
            pass_fds=(trace_fd,),
        )
    finally:
        os.close(trace_fd)
    if result.pop("__stderr_bytes") != 0:
        raise EvidenceError("native parity emitted stderr")
    urls: list[str] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        try:
            url = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvidenceError("native loader trace is malformed") from error
        if not isinstance(url, str) or not url.startswith("file:"):
            raise EvidenceError("native loader trace contains an ambient URL")
        urls.append(url)
    if list((process_root / "tmp").iterdir()):
        raise EvidenceError("native parity left temporary files")
    return result, urls


def _invoke_reference(
    *,
    capsule: Path,
    node: Path,
    process_root: Path,
    request: dict[str, Any],
    metis_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    loader = capsule / ".metis-oracle/native_ts_loader.mjs"
    runner = capsule / ".metis-oracle/runner.ts"
    tsx = metis_root / "tooling/node_modules/tsx/dist/loader.mjs"
    if not tsx.is_file():
        raise EvidenceError("registered TSX comparator is unavailable")
    policy_sha256 = _hash_bytes(REFERENCE_POLICY_TEMPLATE.encode("utf-8"))
    arguments = _runner_arguments(
        capsule=capsule,
        loader=loader,
        runner=runner,
        node=node,
        execution_policy_sha256=policy_sha256,
    )
    command = [
        str(node),
        "--import",
        str(tsx),
        "--input-type=module",
        "--eval",
        _bootstrap(runner, loader, arguments),
    ]
    env = {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "",
        "TMPDIR": str(process_root / "tmp"),
    }
    result = _invoke(
        command=command,
        policy=REFERENCE_POLICY_TEMPLATE,
        process_root=process_root,
        cwd=capsule / "tooling",
        request=request,
        env=env,
    )
    if result.pop("__stderr_bytes") != 0:
        raise EvidenceError("TSX comparator emitted stderr")
    temp_receipt = _snapshot_reference_temp(process_root / "tmp")
    temp_cleanup = _cleanup_reference_temp(process_root / "tmp", temp_receipt)
    return result, temp_receipt, temp_cleanup


def _requests() -> list[dict[str, Any]]:
    candidates_raw = _read_regular(CANDIDATES_PATH, "public smoke candidates")
    registry_raw = _read_regular(REGISTRY_PATH, "public smoke registry")
    try:
        candidates = json.loads(candidates_raw)["candidates"]
        specs = json.loads(registry_raw)["specs"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise EvidenceError("public smoke inputs are malformed") from error
    by_family = {candidate["family"]: candidate for candidate in candidates}
    specs_by_family = {spec["family"]: spec for spec in specs}
    requests: list[dict[str, Any]] = []
    for family, role, source_field in ROLE_FIELDS:
        candidate = by_family[family]
        semantic = specs_by_family[family]["semantic_spec"]
        request = oracles.build_oracle_request(
            candidate[source_field],
            filename=semantic["filename"],
            execution_mode=semantic["execution_mode"],
            endpoint=semantic["endpoint"],
            workspace_sources=semantic["workspace_sources"],
        )
        requests.append(
            {
                "candidate_id": candidate["candidate_id"],
                "family": family,
                "request": request,
                "role": role,
            }
        )
    return requests


def _semantic_result(result: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(result)
    normalized.pop("runtime", None)
    return normalized


def _capture_parity(
    *,
    metis_root: Path,
    node_source: Path,
    capsule_files: dict[str, bytes],
) -> tuple[list[dict[str, Any]], list[str]]:
    native_policy_sha = oracles.CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"]
    reference_policy_sha = _hash_bytes(REFERENCE_POLICY_TEMPLATE.encode("utf-8"))
    temporary_base = Path(tempfile.gettempdir()).resolve()
    if temporary_base.is_relative_to(PROJECT_ROOT) or temporary_base.is_relative_to(metis_root):
        raise EvidenceError("reference parity temporary base is inside a Git checkout")
    with tempfile.TemporaryDirectory(
        prefix="metis-model1-l66-evidence-", dir=temporary_base
    ) as temporary:
        temporary_root = Path(temporary).resolve()
        native_capsule = temporary_root / "native-capsule"
        reference_capsule = temporary_root / "reference-capsule"
        native_files = {
            **capsule_files,
            ".metis-oracle-identity.json": _identity_bytes(native_policy_sha),
        }
        reference_files = {
            **capsule_files,
            ".metis-oracle-identity.json": _identity_bytes(reference_policy_sha),
        }
        _materialize(native_capsule, native_files)
        _materialize(reference_capsule, reference_files)
        runtime_root = temporary_root / "runtime"
        (runtime_root / "bin").mkdir(parents=True)
        runtime_node = runtime_root / "bin/node"
        shutil.copyfile(node_source, runtime_node)
        runtime_node.chmod(0o555)
        (runtime_root / "bin").chmod(0o555)
        runtime_root.chmod(0o555)
        rows: list[dict[str, Any]] = []
        observed_urls: set[str] = set()
        for round_index in range(1, 4):
            for execution_index, request_row in enumerate(_requests(), start=1):
                run_root = temporary_root / f"run-{round_index}-{execution_index}"
                native_root = run_root / "native"
                reference_root = run_root / "reference"
                run_root.mkdir(mode=0o700)
                for root in (native_root, reference_root):
                    root.mkdir(mode=0o700)
                    (root / "tmp").mkdir(mode=0o700)
                native, trace = _invoke_native(
                    capsule=native_capsule,
                    runtime_root=runtime_root,
                    node=runtime_node,
                    process_root=native_root,
                    request=request_row["request"],
                )
                reference, reference_temp, reference_temp_cleanup = _invoke_reference(
                    capsule=reference_capsule,
                    node=node_source,
                    process_root=reference_root,
                    request=request_row["request"],
                    metis_root=metis_root,
                )
                native_semantic = _semantic_result(native)
                reference_semantic = _semantic_result(reference)
                if _canonical(native_semantic) != _canonical(reference_semantic):
                    raise EvidenceError(
                        f"native/TSX parity mismatch at round {round_index} {request_row['role']}"
                    )
                native_diagnostics = native["diagnostics"]
                reference_diagnostics = reference["diagnostics"]
                if _canonical(native_diagnostics) != _canonical(reference_diagnostics):
                    raise EvidenceError(
                        "native/TSX diagnostic mismatch at "
                        f"round {round_index} {request_row['role']}"
                    )
                for url in trace:
                    path = Path(url.removeprefix("file://"))
                    try:
                        relative = path.relative_to(native_capsule).as_posix()
                    except ValueError as error:
                        raise EvidenceError("native trace escaped the capsule") from error
                    observed_urls.add(f"snapshot://{METIS_REVISION}/{METIS_TREE}/{relative}")
                rows.append(
                    {
                        "candidate_id": request_row["candidate_id"],
                        "equal": True,
                        "family": request_row["family"],
                        "input_sha256": _hash(request_row["request"]),
                        "native_diagnostics_sha256": _hash(native_diagnostics),
                        "native_result_sha256": _hash(native_semantic),
                        "native_execution": {
                            "process_fork": "denied",
                            "residual_process_groups": 0,
                            "stderr_bytes": 0,
                            "temporary_entries": 0,
                        },
                        "reference_diagnostics_sha256": _hash(reference_diagnostics),
                        "reference_execution": {
                            "child_process": "allowed",
                            "credit": "reference-only-no-production-authority",
                            "residual_process_groups": 0,
                            "stderr_bytes": 0,
                            "temporary_writes": "bounded-recorded-cleaned",
                        },
                        "reference_result_sha256": _hash(reference_semantic),
                        "reference_temp": reference_temp,
                        "reference_temp_cleanup": reference_temp_cleanup,
                        "role": request_row["role"],
                        "round": round_index,
                    }
                )
                print(
                    "L66 parity "
                    f"{len(rows)}/15 round={round_index} role={request_row['role']} "
                    f"native_urls={len(trace)} native_stderr=0 native_tmp=0 "
                    "native_residual_processes=0 "
                    f"reference_tmp_files={reference_temp['files']} "
                    f"reference_tmp_bytes={reference_temp['bytes']} "
                    "reference_cleanup_residual=0 reference_residual_processes=0",
                    file=sys.stderr,
                    flush=True,
                )
        if len(rows) != 15 or any(not row["equal"] for row in rows):
            raise EvidenceError("reference parity denominator is not exact")
        captured = rows, sorted(observed_urls)
    if temporary_root.exists():
        raise EvidenceError("reference parity left a residual temporary root")
    return captured


def _observed_paths(urls: list[str]) -> set[str]:
    prefix = f"snapshot://{METIS_REVISION}/{METIS_TREE}/"
    paths: set[str] = set()
    for url in urls:
        if not isinstance(url, str) or not url.startswith(prefix):
            raise EvidenceError("observed URL is ambient or outside the pinned snapshot")
        path = url.removeprefix(prefix)
        if not path or path.startswith("/") or ".." in PurePosixPath(path).parts:
            raise EvidenceError("observed URL path is unsafe")
        if path in paths:
            raise EvidenceError("observed URL roster is duplicated")
        paths.add(path)
    if urls != sorted(urls):
        raise EvidenceError("observed URL roster is not ordered")
    return paths


def _build_document(
    *,
    metis_root: Path,
    observed_urls: list[str],
    parity_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, bytes]]:
    toolchain = _tooling_pins(metis_root)
    parser = metis_root / PARSER_PATH
    parser_raw = _read_regular(parser, "registered TypeScript parser")
    parser_manifest = json.loads(
        _read_regular(parser.parents[1] / "package.json", "TypeScript package manifest")
    )
    toolchain["parser"] = {
        "package": f"typescript@{parser_manifest['version']}",
        "path": PARSER_PATH,
        "sha256": _hash_bytes(parser_raw),
    }
    source_rows, source_bytes = _ast_census(metis_root)
    package_rows, package_bytes, package_identities = _package_closure(metis_root)
    observed = _observed_paths(observed_urls)
    static_explanations = {
        "tooling/src/compiler/preview-plan.ts": (
            "reachable only through the erased import-type edge from "
            "tooling/src/language/metis-tenant-settings.ts"
        ),
        "tooling/src/executor/rows.ts": (
            "transitively reachable only behind the erased import-type edge to "
            "tooling/src/compiler/preview-plan.ts"
        ),
    }
    for row in source_rows:
        row["runtime_observed"] = row["path"] in observed
        row["static_only_explanation"] = (
            None if row["runtime_observed"] else static_explanations.get(row["path"])
        )
        if not row["runtime_observed"] and row["static_only_explanation"] is None:
            raise EvidenceError("static-only source has no exact type-only explanation")
    for row in package_rows:
        row["runtime_observed"] = row["path"] in observed
    controls = _control_bytes(metis_root, oracles.CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"])
    capsule_rows = [
        {
            "mode": row["mode"],
            "path": row["path"],
            "role": "git-archive",
            "sha256": row["sha256"],
            "size": row["size"],
        }
        for row in source_rows
    ]
    capsule_rows.extend(
        {
            "mode": row["mode"],
            "path": row["path"],
            "role": "tooling",
            "sha256": row["sha256"],
            "size": row["size"],
        }
        for row in package_rows
    )
    control_roles = {
        ".metis-oracle-identity.json": "tooling",
        ".metis-oracle/native_ts_loader.mjs": "loader",
        ".metis-oracle/runner.ts": "runner",
        "tooling/package-lock.json": "tooling",
        "tooling/package.json": "tooling",
    }
    capsule_rows.extend(
        {
            "mode": 0o444,
            "path": path,
            "role": control_roles[path],
            "sha256": _hash_bytes(raw),
            "size": len(raw),
        }
        for path, raw in controls.items()
    )
    capsule_rows.sort(key=lambda row: row["path"].encode())
    capsule_paths = {row["path"] for row in capsule_rows}
    if observed - capsule_paths:
        raise EvidenceError("observed URL roster escapes the exact capsule")
    if len(source_rows) != 32 or len(package_rows) != 1_790 or len(capsule_rows) != 1_827:
        raise EvidenceError("closure denominator drifted")
    if sum(row["runtime_observed"] for row in source_rows) != 30:
        raise EvidenceError("source observation denominator drifted")
    observed_packages = {row["package"] for row in package_rows if row["runtime_observed"]}
    if len(observed_packages) != 13:
        raise EvidenceError("package observation denominator drifted")
    if len(observed_urls) != 338:
        raise EvidenceError("loader observation denominator drifted")
    if len(parity_rows) != 15 or any(not row.get("equal") for row in parity_rows):
        raise EvidenceError("parity denominator drifted")
    document: dict[str, Any] = {
        "assumptions": {
            "exclusive_host_required": True,
            "executed_preimage_authority": False,
        },
        "capsule_closure": {
            "counts": {
                "ambient_urls": 0,
                "bytes": sum(row["size"] for row in capsule_rows),
                "files": len(capsule_rows),
                "observed_urls": len(observed_urls),
                "outside_urls": 0,
            },
            "observed_urls": observed_urls,
            "observed_urls_sha256": _hash(observed_urls),
            "roster_sha256": _hash(capsule_rows),
            "rows": capsule_rows,
        },
        "evidence_id": "w3-native-loader-closure-parity-v1",
        "metis": {"revision": METIS_REVISION, "tree": METIS_TREE},
        "non_claims": list(NON_CLAIMS),
        "package_closure": {
            "counts": {
                "bytes": sum(row["size"] for row in package_rows),
                "files": len(package_rows),
                "observed_packages": len(observed_packages),
                "packages": len(package_identities),
            },
            "package_identities": package_identities,
            "roster_sha256": _hash(package_rows),
            "rows": package_rows,
        },
        "parity": {
            "counts": {"equal": sum(row["equal"] for row in parity_rows), "rows": 15},
            "normalization": "exact-result-minus-runtime-identity",
            "roster_sha256": _hash(parity_rows),
            "rows": parity_rows,
        },
        "schema_version": 1,
        "source_closure": {
            "counts": {
                "bytes": sum(row["size"] for row in source_rows),
                "edges": sum(len(row["imports"]) for row in source_rows),
                "files": len(source_rows),
                "observed": sum(row["runtime_observed"] for row in source_rows),
                "relative_resolutions": sum(
                    edge["resolved_path"] is not None
                    for row in source_rows
                    for edge in row["imports"]
                ),
                "static_only": sum(not row["runtime_observed"] for row in source_rows),
            },
            "entries": list(SOURCE_ENTRIES),
            "roster_sha256": _hash(source_rows),
            "rows": source_rows,
        },
        "toolchain": toolchain,
    }
    document["manifest_sha256"] = _hash(document)
    all_files = {**source_bytes, **package_bytes, **controls}
    return document, all_files


def _build_blocked_document(metis_root: Path) -> dict[str, Any]:
    toolchain = _tooling_pins(metis_root)
    parser = metis_root / PARSER_PATH
    parser_raw = _read_regular(parser, "registered TypeScript parser")
    try:
        parser_manifest = json.loads(
            _read_regular(parser.parents[1] / "package.json", "TypeScript package manifest")
        )
    except json.JSONDecodeError as error:
        raise EvidenceError("TypeScript package manifest is malformed") from error
    toolchain["parser"] = {
        "package": f"typescript@{parser_manifest['version']}",
        "path": PARSER_PATH,
        "sha256": _hash_bytes(parser_raw),
    }
    source_rows, _ = _ast_census(metis_root)
    package_rows, _, package_identities = _package_closure(metis_root)
    controls = _control_bytes(metis_root, oracles.CAPSULE_EXECUTION_POLICY["sandbox_policy_sha256"])
    capsule_rows = [
        {
            "mode": row["mode"],
            "path": row["path"],
            "role": "git-archive",
            "sha256": row["sha256"],
            "size": row["size"],
        }
        for row in source_rows
    ]
    capsule_rows.extend(
        {
            "mode": row["mode"],
            "path": row["path"],
            "role": "tooling",
            "sha256": row["sha256"],
            "size": row["size"],
        }
        for row in package_rows
    )
    control_roles = {
        ".metis-oracle-identity.json": "tooling",
        ".metis-oracle/native_ts_loader.mjs": "loader",
        ".metis-oracle/runner.ts": "runner",
        "tooling/package-lock.json": "tooling",
        "tooling/package.json": "tooling",
    }
    capsule_rows.extend(
        {
            "mode": 0o444,
            "path": path,
            "role": control_roles[path],
            "sha256": _hash_bytes(raw),
            "size": len(raw),
        }
        for path, raw in controls.items()
    )
    capsule_rows.sort(key=lambda row: row["path"].encode())
    if len(source_rows) != 32 or len(package_rows) != 1_790 or len(capsule_rows) != 1_827:
        raise EvidenceError("blocked static closure denominator drifted")
    document: dict[str, Any] = {
        "assumptions": {
            "exclusive_host_required": True,
            "executed_preimage_authority": False,
        },
        "available": False,
        "capsule_closure": {
            "counts": {
                "bytes": sum(row["size"] for row in capsule_rows),
                "files": len(capsule_rows),
            },
            "roster_sha256": _hash(capsule_rows),
            "rows": capsule_rows,
            "runtime_observation": {
                "available": False,
                "durable_urls": 0,
                "evidence_credit": "none",
            },
        },
        "evidence_id": "w3-native-loader-static-closure-blocked-v1",
        "metis": {"revision": METIS_REVISION, "tree": METIS_TREE},
        "non_claims": list(NON_CLAIMS),
        "package_closure": {
            "counts": {
                "bytes": sum(row["size"] for row in package_rows),
                "files": len(package_rows),
                "packages": len(package_identities),
            },
            "package_identities": package_identities,
            "roster_sha256": _hash(package_rows),
            "rows": package_rows,
        },
        "parity": {
            "available": False,
            "console_only_observations_included": False,
            "durable_rows": 0,
            "evidence_credit": "none",
            "expected_rows": 15,
            "reason": "observation-denominator-drift",
            "status": "blocked",
        },
        "schema_version": 1,
        "source_closure": {
            "counts": {
                "bytes": sum(row["size"] for row in source_rows),
                "edges": sum(len(row["imports"]) for row in source_rows),
                "files": len(source_rows),
                "relative_resolutions": sum(
                    edge["resolved_path"] is not None
                    for row in source_rows
                    for edge in row["imports"]
                ),
            },
            "entries": list(SOURCE_ENTRIES),
            "roster_sha256": _hash(source_rows),
            "rows": source_rows,
        },
        "status": "blocked",
        "toolchain": toolchain,
    }
    document["manifest_sha256"] = _hash(document)
    return document


def _validate_legacy_complete_internal(value: dict[str, Any]) -> None:
    if value.get("schema_version") != 1 or value.get("non_claims") != NON_CLAIMS:
        raise EvidenceError("evidence identity or nonclaims drifted")
    if value.get("assumptions") != {
        "exclusive_host_required": True,
        "executed_preimage_authority": False,
    }:
        raise EvidenceError("evidence threat-boundary assumptions drifted")
    if SCHEMA_PATH.exists():
        try:
            schema = json.loads(_read_regular(SCHEMA_PATH, "evidence schema"))
        except json.JSONDecodeError as error:
            raise EvidenceError("evidence schema is malformed") from error
        errors = sorted(
            Draft202012Validator(schema).iter_errors(value),
            key=lambda item: list(item.path),
        )
        if errors:
            raise EvidenceError(f"evidence violates schema: {errors[0].message}")
    body = {key: item for key, item in value.items() if key != "manifest_sha256"}
    if value.get("manifest_sha256") != _hash(body):
        raise EvidenceError("evidence manifest hash drifted")

    source = value["source_closure"]
    source_rows = source["rows"]
    source_paths = [row["path"] for row in source_rows]
    if source_paths != sorted(source_paths, key=str.encode) or len(set(source_paths)) != len(
        source_paths
    ):
        raise EvidenceError("source closure roster is not exact and ordered")
    source_counts = {
        "bytes": sum(row["size"] for row in source_rows),
        "edges": sum(len(row["imports"]) for row in source_rows),
        "files": len(source_rows),
        "observed": sum(row["runtime_observed"] for row in source_rows),
        "relative_resolutions": sum(
            edge["resolved_path"] is not None for row in source_rows for edge in row["imports"]
        ),
        "static_only": sum(not row["runtime_observed"] for row in source_rows),
    }
    if source["counts"] != source_counts or source["roster_sha256"] != _hash(source_rows):
        raise EvidenceError("source closure counts or roster hash drifted")

    expected_static_only = {
        "tooling/src/compiler/preview-plan.ts": (
            "reachable only through the erased import-type edge from "
            "tooling/src/language/metis-tenant-settings.ts"
        ),
        "tooling/src/executor/rows.ts": (
            "transitively reachable only behind the erased import-type edge to "
            "tooling/src/compiler/preview-plan.ts"
        ),
    }
    actual_static_only = {
        row["path"]: row["static_only_explanation"]
        for row in source_rows
        if not row["runtime_observed"]
    }
    if actual_static_only != expected_static_only:
        raise EvidenceError("source static-only explanation roster drifted")

    package = value["package_closure"]
    package_rows = package["rows"]
    package_paths = [row["path"] for row in package_rows]
    if package_paths != sorted(package_paths, key=str.encode) or len(set(package_paths)) != len(
        package_paths
    ):
        raise EvidenceError("package closure roster is not exact and ordered")
    package_identities = sorted({row["package"] for row in package_rows})
    observed_packages = {row["package"] for row in package_rows if row["runtime_observed"]}
    package_counts = {
        "bytes": sum(row["size"] for row in package_rows),
        "files": len(package_rows),
        "observed_packages": len(observed_packages),
        "packages": len(package_identities),
    }
    if (
        package["counts"] != package_counts
        or package["package_identities"] != package_identities
        or package["roster_sha256"] != _hash(package_rows)
    ):
        raise EvidenceError("package closure counts, identities or roster hash drifted")

    capsule = value["capsule_closure"]
    capsule_rows = capsule["rows"]
    capsule_paths = [row["path"] for row in capsule_rows]
    if capsule_paths != sorted(capsule_paths, key=str.encode) or len(set(capsule_paths)) != len(
        capsule_paths
    ):
        raise EvidenceError("capsule closure roster is not exact and ordered")
    observed_paths = _observed_paths(capsule["observed_urls"])
    capsule_counts = {
        "ambient_urls": 0,
        "bytes": sum(row["size"] for row in capsule_rows),
        "files": len(capsule_rows),
        "observed_urls": len(capsule["observed_urls"]),
        "outside_urls": 0,
    }
    if (
        capsule["counts"] != capsule_counts
        or capsule["roster_sha256"] != _hash(capsule_rows)
        or capsule["observed_urls_sha256"] != _hash(capsule["observed_urls"])
        or not observed_paths.issubset(set(capsule_paths))
    ):
        raise EvidenceError("capsule closure counts, URL set or roster hash drifted")

    capsule_by_path = {row["path"]: row for row in capsule_rows}
    for row in source_rows:
        projected = {
            "mode": row["mode"],
            "path": row["path"],
            "role": "git-archive",
            "sha256": row["sha256"],
            "size": row["size"],
        }
        if capsule_by_path.get(row["path"]) != projected:
            raise EvidenceError("source closure does not project exactly into the capsule")
        if row["runtime_observed"] != (row["path"] in observed_paths):
            raise EvidenceError("source runtime-observation label drifted")
    for row in package_rows:
        projected = {
            "mode": row["mode"],
            "path": row["path"],
            "role": "tooling",
            "sha256": row["sha256"],
            "size": row["size"],
        }
        if capsule_by_path.get(row["path"]) != projected:
            raise EvidenceError("package closure does not project exactly into the capsule")
        if row["runtime_observed"] != (row["path"] in observed_paths):
            raise EvidenceError("package runtime-observation label drifted")

    for role in ("loader", "runner"):
        identity = value["toolchain"][role]
        matching = [row for row in capsule_rows if row["role"] == role]
        if len(matching) != 1 or any(
            matching[0][field] != identity[field] for field in ("mode", "path", "sha256")
        ):
            raise EvidenceError(f"capsule {role} identity drifted")

    parity = value["parity"]
    parity_rows = parity["rows"]
    request_rows = _requests()
    expected_roster = [
        (round_index, request) for round_index in range(1, 4) for request in request_rows
    ]
    if len(parity_rows) != len(expected_roster):
        raise EvidenceError("parity row denominator drifted")
    for row, (round_index, expected) in zip(parity_rows, expected_roster, strict=True):
        _validate_reference_temp_receipt(row["reference_temp"])
        expected_cleanup = {
            "attempted": True,
            "deleted_directories": row["reference_temp"]["directories"],
            "deleted_files": row["reference_temp"]["files"],
            "residual_entries": 0,
        }
        if (
            row["round"] != round_index
            or row["candidate_id"] != expected["candidate_id"]
            or row["family"] != expected["family"]
            or row["role"] != expected["role"]
            or row["input_sha256"] != _hash(expected["request"])
            or not row["equal"]
            or row["native_result_sha256"] != row["reference_result_sha256"]
            or row["native_diagnostics_sha256"] != row["reference_diagnostics_sha256"]
            or row["native_execution"]
            != {
                "process_fork": "denied",
                "residual_process_groups": 0,
                "stderr_bytes": 0,
                "temporary_entries": 0,
            }
            or row["reference_execution"]
            != {
                "child_process": "allowed",
                "credit": "reference-only-no-production-authority",
                "residual_process_groups": 0,
                "stderr_bytes": 0,
                "temporary_writes": "bounded-recorded-cleaned",
            }
            or row["reference_temp_cleanup"] != expected_cleanup
        ):
            raise EvidenceError("parity row identity or equality proof drifted")
    parity_counts = {
        "equal": sum(row["equal"] for row in parity_rows),
        "rows": len(parity_rows),
    }
    if parity["counts"] != parity_counts or parity["roster_sha256"] != _hash(parity_rows):
        raise EvidenceError("parity counts or roster hash drifted")


def _validate_internal(value: dict[str, Any]) -> None:
    if (
        value.get("schema_version") != 1
        or value.get("status") != "blocked"
        or value.get("available") is not False
        or value.get("evidence_id") != "w3-native-loader-static-closure-blocked-v1"
        or value.get("non_claims") != NON_CLAIMS
    ):
        raise EvidenceError("blocked evidence identity, status or nonclaims drifted")
    if value.get("assumptions") != {
        "exclusive_host_required": True,
        "executed_preimage_authority": False,
    }:
        raise EvidenceError("blocked evidence threat-boundary assumptions drifted")
    try:
        schema = json.loads(_read_regular(SCHEMA_PATH, "evidence schema"))
    except json.JSONDecodeError as error:
        raise EvidenceError("evidence schema is malformed") from error
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda item: list(item.path),
    )
    if errors:
        raise EvidenceError(f"evidence violates schema: {errors[0].message}")
    body = {key: item for key, item in value.items() if key != "manifest_sha256"}
    if value.get("manifest_sha256") != _hash(body):
        raise EvidenceError("blocked evidence manifest hash drifted")

    source = value["source_closure"]
    source_rows = source["rows"]
    source_paths = [row["path"] for row in source_rows]
    if source_paths != sorted(source_paths, key=str.encode) or len(source_paths) != len(
        set(source_paths)
    ):
        raise EvidenceError("blocked source closure is not exact and ordered")
    source_counts = {
        "bytes": sum(row["size"] for row in source_rows),
        "edges": sum(len(row["imports"]) for row in source_rows),
        "files": len(source_rows),
        "relative_resolutions": sum(
            edge["resolved_path"] is not None for row in source_rows for edge in row["imports"]
        ),
    }
    if source["counts"] != source_counts or source["roster_sha256"] != _hash(source_rows):
        raise EvidenceError("blocked source closure counts or roster hash drifted")

    package = value["package_closure"]
    package_rows = package["rows"]
    package_paths = [row["path"] for row in package_rows]
    if package_paths != sorted(package_paths, key=str.encode) or len(package_paths) != len(
        set(package_paths)
    ):
        raise EvidenceError("blocked package closure is not exact and ordered")
    package_identities = sorted({row["package"] for row in package_rows})
    package_counts = {
        "bytes": sum(row["size"] for row in package_rows),
        "files": len(package_rows),
        "packages": len(package_identities),
    }
    if (
        package["counts"] != package_counts
        or package["package_identities"] != package_identities
        or package["roster_sha256"] != _hash(package_rows)
    ):
        raise EvidenceError("blocked package closure counts, identities or roster hash drifted")

    capsule = value["capsule_closure"]
    capsule_rows = capsule["rows"]
    capsule_paths = [row["path"] for row in capsule_rows]
    if capsule_paths != sorted(capsule_paths, key=str.encode) or len(capsule_paths) != len(
        set(capsule_paths)
    ):
        raise EvidenceError("blocked capsule closure is not exact and ordered")
    capsule_counts = {
        "bytes": sum(row["size"] for row in capsule_rows),
        "files": len(capsule_rows),
    }
    if (
        capsule["counts"] != capsule_counts
        or capsule["roster_sha256"] != _hash(capsule_rows)
        or capsule["runtime_observation"]
        != {"available": False, "durable_urls": 0, "evidence_credit": "none"}
    ):
        raise EvidenceError("blocked capsule closure counts or roster hash drifted")

    capsule_by_path = {row["path"]: row for row in capsule_rows}
    for row in source_rows:
        if capsule_by_path.get(row["path"]) != {
            "mode": row["mode"],
            "path": row["path"],
            "role": "git-archive",
            "sha256": row["sha256"],
            "size": row["size"],
        }:
            raise EvidenceError("blocked source closure does not project into the capsule")
    for row in package_rows:
        if capsule_by_path.get(row["path"]) != {
            "mode": row["mode"],
            "path": row["path"],
            "role": "tooling",
            "sha256": row["sha256"],
            "size": row["size"],
        }:
            raise EvidenceError("blocked package closure does not project into the capsule")
    for role in ("loader", "runner"):
        identity = value["toolchain"][role]
        matching = [row for row in capsule_rows if row["role"] == role]
        if len(matching) != 1 or any(
            matching[0][field] != identity[field] for field in ("mode", "path", "sha256")
        ):
            raise EvidenceError(f"blocked capsule {role} identity drifted")
    if value["parity"] != {
        "available": False,
        "console_only_observations_included": False,
        "durable_rows": 0,
        "evidence_credit": "none",
        "expected_rows": 15,
        "reason": "observation-denominator-drift",
        "status": "blocked",
    }:
        raise EvidenceError("blocked parity STOP contract drifted")


def load_evidence_manifest(path: Path = EVIDENCE_PATH) -> dict[str, Any]:
    try:
        raw = _read_regular(path, "native evidence manifest")
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise EvidenceError("native evidence manifest is malformed") from error
    if raw != _canonical(value) + b"\n":
        raise EvidenceError("native evidence manifest is not canonical")
    _validate_internal(value)
    return value


def verify_evidence_document(value: dict[str, Any]) -> None:
    _validate_internal(value)
    registered = load_evidence_manifest()
    if _canonical(value) != _canonical(registered):
        raise EvidenceError("evidence document differs from the registered receipt")


def _recompute_blocked(metis_root: Path) -> dict[str, Any]:
    document = _build_blocked_document(metis_root)
    _validate_internal(document)
    return document


def emit_evidence(path: Path, *, metis_root: Path = DEFAULT_METIS_ROOT) -> None:
    document = _recompute_blocked(metis_root.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(document) + b"\n")


def verify_evidence(path: Path, *, metis_root: Path = DEFAULT_METIS_ROOT) -> None:
    expected = _recompute_blocked(metis_root.resolve())
    actual = load_evidence_manifest(path)
    if _canonical(actual) != _canonical(expected):
        raise EvidenceError("evidence file differs from deterministic recomputation")


def capture_evidence(path: Path, *, metis_root: Path = DEFAULT_METIS_ROOT) -> None:
    del path, metis_root
    raise EvidenceError("parity capture is permanently closed after observation-denominator-drift")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--capture", type=Path)
    operation.add_argument("--emit", type=Path)
    operation.add_argument("--verify", type=Path)
    parser.add_argument("--metis-root", type=Path, default=DEFAULT_METIS_ROOT)
    arguments = parser.parse_args(argv)
    try:
        if arguments.capture is not None:
            capture_evidence(arguments.capture, metis_root=arguments.metis_root)
        elif arguments.emit is not None:
            emit_evidence(arguments.emit, metis_root=arguments.metis_root)
        else:
            verify_evidence(arguments.verify, metis_root=arguments.metis_root)
    except EvidenceError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
