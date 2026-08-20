"""Offline, deterministic dataset contracts and a guarded JSONL writer."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from metis_model1.provenance import NonJsonValueError, canonical_json_bytes, canonical_json_hash
from metis_model1.provenance import example_id as make_example_id

FAMILIES = frozenset({f"F-{number}" for number in range(1, 7)})
SPLITS = frozenset({"train", "dev", "internal_test", "frozen"})
SENSITIVITIES = frozenset({"public", "internal", "restricted"})
ORACLE_RESULTS = frozenset({"pass", "fail", "pending", "not_applicable"})
ORACLE_NAMES = frozenset(
    {
        "parse",
        "link",
        "validate",
        "compile",
        "semantic",
        "patch_minimality",
        "diagnostic",
        "ir",
        "wire",
        "golden",
        "migration_pair",
        "ast",
        "human",
    }
)
REQUIRED_ORACLES_BY_FAMILY = {
    "F-1": frozenset({"parse", "link", "validate", "compile", "semantic"}),
    "F-2": frozenset({"patch_minimality", "parse", "link", "validate", "compile", "semantic"}),
    "F-3": frozenset({"diagnostic", "parse", "link", "validate", "compile", "semantic"}),
    "F-4": frozenset({"compile", "ir", "wire", "golden", "semantic"}),
    "F-5": frozenset({"migration_pair", "parse", "link", "validate", "compile", "semantic"}),
    "F-6": frozenset({"ast", "ir", "semantic", "human"}),
}


def _schema_path(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / name


def load_schema(name: str = "dataset-example.schema.json") -> dict[str, Any]:
    with _schema_path(name).open(encoding="utf-8") as handle:
        return json.load(handle)


def _schema_errors(instance: Any, schema: Mapping[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in errors
    ]


def _hash_string(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value[7:]
    if len(digest) != 64:
        return False
    try:
        int(digest, 16)
    except ValueError:
        return False
    return True


def _example_semantic_errors(example: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        expected_id = make_example_id(
            example["schema_version"], example["input"], example["output"]
        )
    except (NonJsonValueError, TypeError, ValueError) as error:
        errors.append(f"input/output cannot form a canonical example ID: {error}")
        expected_id = None
    if expected_id is not None and example["example_id"] != expected_id:
        errors.append("example_id does not match canonical schema_version/input/output")

    provenance = example["provenance"]
    parents = provenance["parents"]
    if len(parents) != len(set(parents)):
        errors.append("provenance.parents must not contain duplicates")

    oracles = example["oracles"]
    names = [record["name"] for record in oracles]
    if len(names) != len(set(names)):
        errors.append("oracle names must be unique")
    if example["status"] == "accepted" and any(
        record["applicable"] and record["result"] == "pending" for record in oracles
    ):
        errors.append("applicable oracle cannot be pending")
    for record in oracles:
        applicable = record["applicable"]
        result = record["result"]
        if not applicable and result != "not_applicable":
            errors.append(f"non-applicable oracle {record['name']} must be not_applicable")
        if applicable and result not in {"pass", "fail", "pending"}:
            errors.append(f"applicable oracle {record['name']} has an invalid result")
        if applicable and result in {"pass", "fail"} and not _hash_string(record["evidence_hash"]):
            errors.append(f"applicable oracle {record['name']} needs an evidence hash")
        if not applicable and record["evidence_hash"] is not None:
            errors.append(f"non-applicable oracle {record['name']} must not have evidence")

    if example["status"] == "accepted" and example["positive"]:
        required = REQUIRED_ORACLES_BY_FAMILY[example["task_family"]]
        declared = set(names)
        missing = sorted(required - declared)
        undeclared = sorted(declared - required)
        if missing:
            errors.append(
                "accepted positive example is missing required oracles: " + ",".join(missing)
            )
        if undeclared:
            errors.append(
                "accepted positive example has undeclared oracles: " + ",".join(undeclared)
            )
        if declared == required and any(not record["applicable"] for record in oracles):
            errors.append("all required oracles for an accepted positive must be applicable")

    if example["sensitivity"] not in SENSITIVITIES:
        errors.append("prohibited sensitivity is not permitted")
    if example["status"] == "accepted" and example["positive"]:
        assistants = [message for message in example["messages"] if message["role"] == "assistant"]
        if len(assistants) != 1 or example["messages"][-1]["role"] != "assistant":
            errors.append("accepted positive example requires exactly one final assistant message")
        elif (
            not isinstance(example["output"].get("assistant_content"), str)
            or not example["output"]["assistant_content"]
            or example["output"]["assistant_content"] != assistants[0]["content"]
        ):
            errors.append("output.assistant_content must equal the final assistant message")
        applicable = [record for record in oracles if record["applicable"]]
        if not applicable or any(record["result"] != "pass" for record in applicable):
            errors.append("accepted positive example requires every applicable oracle to pass")
        semantic = [record for record in applicable if record["name"] in {"semantic", "human"}]
        if not semantic or not any(record["result"] == "pass" for record in semantic):
            errors.append("accepted positive example requires a passing semantic or human oracle")
    if example["status"] == "accepted" and any(record["result"] == "pending" for record in oracles):
        errors.append("accepted example cannot contain a pending oracle")
    return errors


def _sft_materialization_errors(examples: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        f"example[{index}] is not materializable SFT: status=accepted and positive=true required"
        for index, example in enumerate(examples)
        if example.get("status") != "accepted" or example.get("positive") is not True
    ]


def validate_example(example: Any, schema: Mapping[str, Any] | None = None) -> list[str]:
    """Return all schema and semantic errors for one dataset example."""

    if not isinstance(example, Mapping):
        return ["example must be an object"]
    schema_errors = _schema_errors(example, schema or load_schema())
    if schema_errors:
        return schema_errors
    return _example_semantic_errors(example)


def _split_errors(examples: Sequence[Mapping[str, Any]]) -> list[str]:
    errors: list[str] = []
    ids = [example.get("example_id") for example in examples if isinstance(example, Mapping)]
    comparable_ids = [example_id for example_id in ids if isinstance(example_id, str)]
    if len(comparable_ids) != len(set(comparable_ids)):
        errors.append("duplicate example_id")
    example_rosters = {
        example["example_id"]: (
            example["split"],
            example["provenance"]["leakage_group"],
        )
        for example in examples
        if isinstance(example, Mapping)
        and isinstance(example.get("example_id"), str)
        and isinstance(example.get("split"), str)
        and isinstance(example.get("provenance"), Mapping)
        and isinstance(example["provenance"].get("leakage_group"), str)
    }
    parent_asset_splits: dict[str, str] = {}
    group_splits: dict[str, str] = {}
    for example in examples:
        if not isinstance(example, Mapping):
            continue
        split = example.get("split")
        provenance = example.get("provenance")
        if not isinstance(split, str) or not isinstance(provenance, Mapping):
            continue
        group = provenance.get("leakage_group")
        if not isinstance(group, str):
            continue
        previous = group_splits.setdefault(group, split)
        if previous != split:
            errors.append(f"leakage_group crosses split: {group}")
        parents = provenance.get("parents", [])
        if not isinstance(parents, list):
            continue
        for parent in parents:
            if not isinstance(parent, str):
                continue
            parent_example = example_rosters.get(parent)
            if parent_example is not None:
                parent_example_split, parent_example_group = parent_example
                if parent_example_split != split:
                    errors.append(
                        f"provenance parent crosses split: {parent} (parent example crosses split)"
                    )
                if parent_example_group != group:
                    errors.append(
                        f"provenance parent example must share the child leakage_group: {parent}"
                    )
                continue
            previous = parent_asset_splits.setdefault(parent, split)
            if previous != split:
                errors.append(f"provenance parent crosses split: {parent}")
    return errors


def _jsonl_bytes(examples: Sequence[Mapping[str, Any]]) -> bytes:
    ordered = sorted(examples, key=lambda example: example["example_id"])
    return b"".join(canonical_json_bytes(example) + b"\n" for example in ordered)


def dataset_manifest(
    examples: Iterable[Mapping[str, Any]], *, split_manifest_id: str | None = None
) -> dict[str, Any]:
    """Build deterministic counts and payload hash for a validated collection."""

    rows = list(examples)
    errors = _split_errors(rows)
    for index, row in enumerate(rows):
        errors.extend(f"example[{index}]: {error}" for error in validate_example(row))
    errors.extend(_sft_materialization_errors(rows))
    if errors:
        raise ValueError("invalid dataset: " + "; ".join(errors))
    if split_manifest_id is not None:
        if not _hash_string(split_manifest_id):
            raise ValueError("split_manifest_id must be a sha256 identity")
        expected_split_manifest_id = "sha256:" + canonical_json_hash(_split_manifest_body(rows))
        if split_manifest_id != expected_split_manifest_id:
            raise ValueError("split_manifest_id does not match the deterministic split manifest")
    by_split = Counter(row["split"] for row in rows)
    by_family = Counter(row["task_family"] for row in rows)
    manifest = {
        "schema_version": 1,
        "example_count": len(rows),
        "counts_by_split": {split: by_split.get(split, 0) for split in sorted(SPLITS)},
        "counts_by_family": {family: by_family.get(family, 0) for family in sorted(FAMILIES)},
        "example_ids": sorted(row["example_id"] for row in rows),
        "jsonl_sha256": "sha256:" + hashlib.sha256(_jsonl_bytes(rows)).hexdigest(),
    }
    if split_manifest_id is not None:
        manifest["split_manifest_id"] = split_manifest_id
    return manifest


def validate_dataset(
    examples: Iterable[Mapping[str, Any]], manifest: Mapping[str, Any] | None = None
) -> list[str]:
    """Validate examples, leakage boundaries, and (when given) exact manifest claims."""

    rows = list(examples)
    errors = _split_errors(rows)
    for index, row in enumerate(rows):
        errors.extend(f"example[{index}]: {error}" for error in validate_example(row))
    if manifest is not None:
        errors.extend(_sft_materialization_errors(rows))
        try:
            errors.extend(_schema_errors(manifest, load_schema("dataset-manifest.schema.json")))
        except (KeyError, TypeError):
            errors.append("dataset manifest is not an object")
        if not errors:
            expected = dataset_manifest(rows)
            for field in (
                "example_count",
                "counts_by_split",
                "counts_by_family",
                "example_ids",
                "jsonl_sha256",
            ):
                if manifest.get(field) != expected[field]:
                    errors.append(f"dataset manifest field is not deterministic: {field}")
            if "split_manifest_id" in manifest:
                split_id = build_split_manifest(rows)["split_manifest_id"]
                if manifest["split_manifest_id"] != split_id:
                    errors.append("dataset manifest split_manifest_id is not deterministic")
    return errors


def _split_manifest_body(examples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    splits: dict[str, dict[str, list[str]]] = {
        split: {"example_ids": [], "leakage_groups": []} for split in sorted(SPLITS)
    }
    for row in examples:
        bucket = splits[row["split"]]
        bucket["example_ids"].append(row["example_id"])
        bucket["leakage_groups"].append(row["provenance"]["leakage_group"])
    for bucket in splits.values():
        bucket["example_ids"] = sorted(bucket["example_ids"])
        bucket["leakage_groups"] = sorted(set(bucket["leakage_groups"]))
    return {"schema_version": 1, "assignment": "leakage_group", "splits": splits}


def build_split_manifest(examples: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Create a deterministic leakage-group assignment manifest."""

    rows = list(examples)
    errors = validate_dataset(rows)
    if errors:
        raise ValueError("invalid dataset: " + "; ".join(errors))
    body = _split_manifest_body(rows)
    return {**body, "split_manifest_id": "sha256:" + canonical_json_hash(body)}


def validate_split_manifest(
    examples: Iterable[Mapping[str, Any]], manifest: Mapping[str, Any]
) -> list[str]:
    """Check a split manifest against its examples and immutable ID."""

    errors = _schema_errors(manifest, load_schema("split-manifest.schema.json"))
    if errors:
        return errors
    expected = build_split_manifest(examples)
    if dict(manifest) != expected:
        return ["split manifest is not a deterministic representation of examples"]
    return []


def build_dataset(
    examples: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Sort and validate examples, returning rows plus their deterministic manifest."""

    rows = sorted(
        (dict(example) for example in examples),
        key=lambda example: example.get("example_id", ""),
    )
    errors = validate_dataset(rows)
    if errors:
        raise ValueError("invalid dataset: " + "; ".join(errors))
    return rows, dataset_manifest(rows)


def _resolved_destination(
    destination: str | os.PathLike[str],
    artifact_root: str | os.PathLike[str] | None,
) -> tuple[Path, Path]:
    repository = Path(__file__).resolve().parents[2]
    default_root = repository / "datasets" / "materialized"
    root = default_root if artifact_root is None else Path(artifact_root).expanduser().absolute()
    root.mkdir(parents=True, exist_ok=True)
    # Existing symlink components are never trusted, even if they resolve below
    # the permitted root.
    cursor = root
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise ValueError("artifact root may not contain symlinks")
        cursor = cursor.parent
    target = Path(destination)
    if not target.is_absolute():
        target = root / target
    if target.is_symlink():
        raise ValueError("destination may not be a symlink")
    cursor = target.parent
    while cursor != cursor.parent and cursor != root:
        if cursor.is_symlink():
            raise ValueError("destination parent may not be a symlink")
        cursor = cursor.parent
    resolved_root = root.resolve()
    resolved_target = target.resolve(strict=False)
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("destination escapes the artifact root") from error
    # Explicit roots are allowed outside the repository; inside it, only the
    # ignored materialized payload directory is a legal destination.
    try:
        resolved_target.relative_to(repository.resolve())
    except ValueError:
        pass
    else:
        try:
            resolved_target.relative_to(default_root.resolve())
        except ValueError as error:
            raise ValueError(
                "dataset payload cannot be written inside tracked repository paths"
            ) from error
    if target.suffix.lower() != ".jsonl":
        raise ValueError("dataset payload destination must be a .jsonl file")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target, resolved_target


def write_dataset_jsonl(
    examples: Iterable[Mapping[str, Any]],
    destination: str | os.PathLike[str],
    *,
    artifact_root: str | os.PathLike[str] | None = None,
) -> Path:
    """Atomically write canonical JSONL under a permitted local artifact root."""

    rows, _ = build_dataset(examples)
    target, _ = _resolved_destination(destination, artifact_root)
    payload = _jsonl_bytes(rows)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        with suppress(FileNotFoundError):
            os.unlink(temporary)
        raise
    return target


def write_dataset(*args: Any, **kwargs: Any) -> Path:
    """Compatibility alias for :func:`write_dataset_jsonl`."""

    return write_dataset_jsonl(*args, **kwargs)


validate_dataset_examples = validate_dataset
write_jsonl_atomic = write_dataset_jsonl
