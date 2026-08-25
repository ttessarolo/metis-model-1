"""Git-object-only census for the pinned Metis grammar and stdlib registry.

The census is deliberately structural.  It proves that the pinned source blobs
contain the registered grammar/stdlib inventory; it does not execute Metis,
read tenant payloads, or authorize model/training/accuracy claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "schemas/grammar-stdlib-pin.schema.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-pin-v1.json"
DEFAULT_GIT_DIR = Path("/Users/tommasotessarolo/Developer/ares-matioska/metis/.git")
EVIDENCE_PATHS = {
    "grammar": "tooling/src/language/metis.langium",
    "generated_grammar": "tooling/src/language/generated/grammar.ts",
    "stdlib": "tooling/src/language/stdlib-schema.ts",
    "version": "tooling/src/language/version.ts",
    "guard_eval": "tooling/src/compiler/guard-eval.ts",
    "corpus_validation_test": "tooling/test/corpus-validation.ts",
    "time_test": "tooling/test/time-rule.ts",
    "compiler_regression_test": "tooling/test/compiler-regression.ts",
}


class GrammarStdlibCoverageError(ValueError):
    """Raised when the pinned source census cannot be verified."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise GrammarStdlibCoverageError(f"non-canonical JSON: {error}") from error


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GrammarStdlibCoverageError(f"{label} is unavailable or invalid") from error
    if not isinstance(value, dict):
        raise GrammarStdlibCoverageError(f"{label} must be an object")
    return value


def load_pin(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Load and schema-validate the tracked census pin."""

    root = root.resolve(strict=True)
    schema = _load_json(root / SCHEMA_PATH.relative_to(PROJECT_ROOT), "pin schema")
    manifest = _load_json(root / MANIFEST_PATH.relative_to(PROJECT_ROOT), "pin manifest")
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:  # noqa: BLE001 - fail closed on malformed schema
        raise GrammarStdlibCoverageError(f"pin schema is invalid: {error}") from error
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise GrammarStdlibCoverageError(f"pin schema mismatch at {location}: {first.message}")
    return manifest


def _git_env() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }


def _run_git(git_dir: Path, *args: str, text: bool = True) -> str | bytes:
    """Run a local object-database command without a worktree or network."""

    git_dir = git_dir.resolve(strict=True)
    if not git_dir.name == ".git":
        raise GrammarStdlibCoverageError("git_dir must name the external repository .git directory")
    command = ["/usr/bin/git", "--git-dir", str(git_dir), *args]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=text,
            env=_git_env(),
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise GrammarStdlibCoverageError(f"Git object command failed: {' '.join(args)}") from error
    return result.stdout


def _blob_oid(git_dir: Path, revision: str, path: str) -> str:
    raw = _run_git(git_dir, "ls-tree", "-z", revision, "--", path)
    if not isinstance(raw, str):
        raise GrammarStdlibCoverageError("Git tree listing was not text")
    entries = [item for item in raw.split("\0") if item]
    if len(entries) != 1:
        raise GrammarStdlibCoverageError(f"expected exactly one Git tree entry for {path}")
    match = re.fullmatch(r"\d+ blob ([0-9a-f]{40})\t(.+)", entries[0])
    if not match or match.group(2) != path:
        raise GrammarStdlibCoverageError(f"Git tree entry mismatch for {path}")
    return match.group(1)


def _blob(git_dir: Path, oid: str) -> bytes:
    raw = _run_git(git_dir, "cat-file", "blob", oid, text=False)
    if not isinstance(raw, bytes):
        raise GrammarStdlibCoverageError("Git blob was not bytes")
    return raw


def _grammar_inventory(raw: bytes) -> dict[str, Any]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise GrammarStdlibCoverageError("grammar blob is not UTF-8") from error
    productions: list[dict[str, Any]] = []
    terminals: list[dict[str, Any]] = []
    top_level: list[str] = []
    in_top_level = False
    top_text = ""
    production_pattern = re.compile(
        r"^(entry\s+)?([A-Za-z][A-Za-z0-9_]*)(?:\s+(returns|infers)\s+[^:]+)?\s*:"
    )
    terminal_pattern = re.compile(r"^(hidden\s+)?terminal\s+([A-Za-z][A-Za-z0-9_]*)\b")
    for line_number, line in enumerate(lines, 1):
        match = production_pattern.match(line)
        if match:
            productions.append(
                {
                    "line": line_number,
                    "name": match.group(2),
                    "kind": match.group(3) or "normal",
                    "entry": bool(match.group(1)),
                }
            )
        match = terminal_pattern.match(line)
        if match:
            terminals.append(
                {"line": line_number, "name": match.group(2), "hidden": bool(match.group(1))}
            )
        if line.startswith("TopLevel:"):
            in_top_level = True
            top_text = line.split(":", 1)[1]
        elif in_top_level:
            top_text += " " + line
        if in_top_level and ";" in line:
            in_top_level = False
            top_text = top_text.split(";", 1)[0]
            top_level = [item.strip() for item in top_text.split("|") if item.strip()]
    return {
        "production_count": len(productions),
        "returns_count": sum(item["kind"] == "returns" for item in productions),
        "infers_count": sum(item["kind"] == "infers" for item in productions),
        "productions": productions,
        "terminal_count": len(terminals),
        "hidden_terminal_count": sum(item["hidden"] for item in terminals),
        "terminals": terminals,
        "top_level_alternatives": top_level,
    }


def _stdlib_inventory(raw: bytes) -> dict[str, Any]:
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GrammarStdlibCoverageError("stdlib blob is not UTF-8") from error
    starts = list(
        re.finditer(
            r"\n    \{\n        name: '([^']+)',\n        nature: '(ambient|pure)',", source
        )
    )
    modules: list[dict[str, Any]] = []
    for index, match in enumerate(starts):
        section_end = (
            starts[index + 1].start()
            if index + 1 < len(starts)
            else source.index("\n];", match.end())
        )
        section = source[match.start() : section_end]
        members = [
            {"name": name, "type": member_type}
            for name, member_type in re.findall(
                r"\{ name: '([^']+)', type: '(string|number)',", section
            )
        ]
        settings = [
            {"group": group, "key": key, "type": setting_type, "default": default}
            for group, key, setting_type, default in re.findall(
                r"group: '([^']+)', key: '([^']+)', type: '(string|number)', default: '([^']+)'",
                section,
            )
        ]
        modules.append(
            {
                "name": match.group(1),
                "nature": match.group(2),
                "members": members,
                "settings": settings,
            }
        )
    return {
        "module_count": len(modules),
        "member_count": sum(len(module["members"]) for module in modules),
        "setting_count": sum(len(module["settings"]) for module in modules),
        "modules": modules,
    }


def _stdlib_exports(raw: bytes) -> list[str]:
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GrammarStdlibCoverageError("stdlib blob is not UTF-8") from error
    return re.findall(
        r"^export (?:type|interface|const|function) ([A-Za-z][A-Za-z0-9_]*)", source, re.MULTILINE
    )


def _language_version(raw: bytes) -> str:
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GrammarStdlibCoverageError("version blob is not UTF-8") from error
    match = re.search(r"^export const METIS_LANGUAGE_VERSION = '([^']+)'", source, re.MULTILINE)
    if not match:
        raise GrammarStdlibCoverageError("language version declaration is missing")
    return match.group(1)


def _evidence(git_dir: Path, revision: str, item: dict[str, Any]) -> dict[str, Any]:
    oid = _blob_oid(git_dir, revision, item["path"])
    if oid != item["blob_oid"]:
        raise GrammarStdlibCoverageError(f"blob OID drift for {item['id']}")
    raw = _blob(git_dir, oid)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != item["sha256"]:
        raise GrammarStdlibCoverageError(f"blob SHA-256 drift for {item['id']}")
    return {
        "id": item["id"],
        "path": item["path"],
        "blob_oid": oid,
        "sha256": digest,
        "bytes": len(raw),
        "lines": len(raw.decode("utf-8").splitlines()),
    }


def validate_pin_contract(root: Path = PROJECT_ROOT) -> list[str]:
    """Validate the tracked manifest without contacting or reading Metis."""

    try:
        manifest = load_pin(root)
    except GrammarStdlibCoverageError as error:
        return [str(error)]
    errors: list[str] = []
    grammar = manifest["grammar"]
    if grammar["production_count"] != len(grammar["production_names"]):
        errors.append("grammar production count/list mismatch")
    if grammar["terminal_count"] != len(grammar["terminal_names"]):
        errors.append("grammar terminal count/list mismatch")
    stdlib = manifest["stdlib"]
    inventory = stdlib["inventory"]
    if stdlib["module_count"] != len(inventory["modules"]):
        errors.append("stdlib module count/list mismatch")
    if stdlib["member_count"] != sum(len(item["members"]) for item in inventory["modules"]):
        errors.append("stdlib member count/list mismatch")
    if stdlib["setting_count"] != sum(len(item["settings"]) for item in inventory["modules"]):
        errors.append("stdlib setting count/list mismatch")
    production_names = set(grammar["production_names"])
    for group_name, group in grammar["construct_groups"].items():
        if group["count"] != len(group["productions"]):
            errors.append(f"construct group count/list mismatch: {group_name}")
        if len(group["productions"]) != len(set(group["productions"])):
            errors.append(f"construct group has duplicates: {group_name}")
        if not set(group["productions"]).issubset(production_names):
            errors.append(f"construct group has unknown production: {group_name}")
    evidence_ids = [item["id"] for item in manifest["evidence"]]
    if len(evidence_ids) != len(set(evidence_ids)):
        errors.append("evidence IDs are not distinct")
    if {item["id"]: item["path"] for item in manifest["evidence"]} != EVIDENCE_PATHS:
        errors.append("evidence ID/path roster mismatch")
    return errors


def census(
    git_dir: Path = DEFAULT_GIT_DIR,
    root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    """Recompute the manifest census from Git blobs only."""

    errors = validate_pin_contract(root)
    if errors:
        raise GrammarStdlibCoverageError("; ".join(errors))
    manifest = load_pin(root)
    revision = manifest["revision"]
    tree = _run_git(git_dir, "rev-parse", f"{revision}^{{tree}}")
    if not isinstance(tree, str) or tree.strip() != manifest["tree"]:
        raise GrammarStdlibCoverageError("pinned Git tree mismatch")
    _run_git(git_dir, "cat-file", "-e", f"{revision}^{{commit}}")

    evidence = [_evidence(git_dir, revision, item) for item in manifest["evidence"]]
    blobs = {item["id"]: _blob(git_dir, item["blob_oid"]) for item in manifest["evidence"]}
    grammar = _grammar_inventory(blobs["grammar"])
    stdlib = _stdlib_inventory(blobs["stdlib"])
    version = _language_version(blobs["version"])
    if grammar["production_count"] != manifest["grammar"]["production_count"]:
        raise GrammarStdlibCoverageError("grammar production count drift")
    if grammar["top_level_alternatives"] != manifest["grammar"]["top_level_alternatives"]:
        raise GrammarStdlibCoverageError("grammar top-level roster drift")
    if [item["name"] for item in grammar["productions"]] != manifest["grammar"]["production_names"]:
        raise GrammarStdlibCoverageError("grammar production roster drift")
    if [item["name"] for item in grammar["terminals"]] != manifest["grammar"]["terminal_names"]:
        raise GrammarStdlibCoverageError("grammar terminal roster drift")
    if stdlib != manifest["stdlib"]["inventory"]:
        raise GrammarStdlibCoverageError("stdlib inventory drift")
    if _stdlib_exports(blobs["stdlib"]) != manifest["stdlib"]["public_exports"]:
        raise GrammarStdlibCoverageError("stdlib public export roster drift")
    if version != manifest["language_version"]:
        raise GrammarStdlibCoverageError("language version evidence drift")

    current = manifest["comparison"]
    current_tree = _run_git(git_dir, "rev-parse", f"{current['revision']}^{{tree}}")
    if not isinstance(current_tree, str) or current_tree.strip() != current["tree"]:
        raise GrammarStdlibCoverageError("comparison Git tree mismatch")
    comparison_blobs: dict[str, str] = {}
    for item in manifest["evidence"]:
        comparison_blobs[item["id"]] = _blob_oid(git_dir, current["revision"], item["path"])
        if comparison_blobs[item["id"]] != item["blob_oid"]:
            raise GrammarStdlibCoverageError(f"comparison blob drift for {item['id']}")
    return {
        "status": "valid",
        "revision": revision,
        "tree": manifest["tree"],
        "comparison_revision": current["revision"],
        "comparison_tree": current["tree"],
        "evidence": evidence,
        "grammar": grammar,
        "stdlib": stdlib,
        "stdlib_public_exports": manifest["stdlib"]["public_exports"],
        "language_version": version,
        "policy": manifest["policy"],
        "nonclaims": manifest["nonclaims"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m metis_model1.grammar_stdlib_coverage")
    parser.add_argument("command", nargs="?", choices=("census", "validate"), default="census")
    parser.add_argument("--git-dir", type=Path, default=DEFAULT_GIT_DIR)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            errors = validate_pin_contract(args.root)
            result: dict[str, Any] = {
                "status": "valid" if not errors else "invalid",
                "errors": errors,
            }
            ok = not errors
        else:
            result = census(args.git_dir, args.root)
            ok = True
    except GrammarStdlibCoverageError as error:
        result = {"status": "invalid", "errors": [str(error)]}
        ok = False
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    elif ok:
        print(
            "GRAMMAR_STDLIB "
            f"{result['status'].upper()} revision={result.get('revision', 'manifest')}"
        )
    else:
        for error in result["errors"]:
            print(f"ERROR {error}")
        print("GRAMMAR_STDLIB INVALID")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
