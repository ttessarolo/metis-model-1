# ruff: noqa: E501
"""Deterministic, public-synthetic seed builder for INITIAL_LOCAL_QLORA_V1.

This module deliberately has no model dependency. ``materialize`` is the only
operation which executes the pinned catalog-domain archive oracle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from metis_model1 import catalog_maintenance_pin as pin
from metis_model1.catalog_maintenance_probe import (
    CatalogMaintenanceProbeError,
    _describe_source_in_snapshot,
)
from metis_model1.catalog_retrieval import CatalogRetrievalError
from metis_model1.catalog_retrieval_refresh import (
    CatalogRetrievalRefreshError,
    _pinned_snapshot,
)
from metis_model1.dataset import (
    build_split_manifest,
    dataset_manifest,
    validate_dataset,
    validate_split_manifest,
)
from metis_model1.provenance import canonical_json_bytes, example_id

LANGUAGE_VERSION = "0.43"
SURFACE_REVISION = "1f7eaae9d803edc90f51ff492ea443f18570015e"
PINNED_REVISION = "5e112f9148f40e7e792052e896c5a9efe8eaf0a2"
PINNED_TREE = "41c7a2b6890fa42d8123bd93f6560d0b9bfae8af"
WAVE = "INITIAL_LOCAL_QLORA_V1"
NAMESPACE = "initial-local-qlora-v1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts/initial-local-qlora-v1"
COUNTS = {"train": {"F-1": 22, "F-2": 21, "F-3": 21}, "dev": {"F-1": 5, "F-2": 5, "F-3": 6}}
EXCLUDED_MARKERS = (
    "prior benchmark assets",
    "prior prompt assets",
    "prior model outputs",
    "case-specific derivatives",
)
EXCLUSIONS_SHA256 = "sha256:e318e0af085f74dced1cb6c920608882219f5ad3154d60e60496dcd8f236c020"
HASH_PREFIX = "sha256:"
B12_ROSTER = PROJECT_ROOT / "artifacts/w5-xs/2026-08-24-delivery/b12-roster-v2.json"
B12_ROSTER_SHA256 = "sha256:1459d1fa171b9f124c016aabed559081c9d3e7ca34db6d31b7285e692b175e6d"


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _raw_hash(raw: bytes) -> str:
    return HASH_PREFIX + hashlib.sha256(raw).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return HASH_PREFIX + digest.hexdigest()


def _is_hash(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith(HASH_PREFIX):
        return False
    digest = value[len(HASH_PREFIX) :]
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def _write_fsynced(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _dataset_target(destination: str | os.PathLike[str]) -> Path:
    root = ARTIFACT_ROOT.absolute()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("artifact root must be a regular directory")
    target = Path(destination).absolute()
    expected = root / "dataset"
    if target.resolve(strict=False) != expected.resolve(strict=False):
        raise ValueError("dataset destination is not the fixed ignored artifact path")
    cursor = target.parent
    while cursor != PROJECT_ROOT.parent:
        if cursor.exists() and cursor.is_symlink():
            raise ValueError("dataset destination crosses a symlink")
        if cursor == cursor.parent:
            break
        cursor = cursor.parent
    return target


def _source(family: str, number: int, variant: str = "fixed") -> str:
    name = f"atlas_{family[-1].lower()}_{number:02d}"
    heldout = number >= 32
    if family == "F-1":
        if heldout:
            return f'metis {LANGUAGE_VERSION}\ncatalog public.video {{\n  driver opensearch\n  index "cosmos_audio_{number:02d}"\n  id clip_{number:02d}\n  fields {{\n    state keyword enum(4)\n    clip_{number:02d} keyword\n  }}\n}}\n'
        return f'metis {LANGUAGE_VERSION}\ncatalog public.video {{\n  driver opensearch\n  index "{name}"\n  id asset_{number:02d}\n  fields {{\n    asset_{number:02d} keyword\n    state keyword enum(3)\n  }}\n}}\n'
    if family == "F-2":
        if heldout:
            before = f'metis {LANGUAGE_VERSION}\ncatalog public.video {{\n  driver opensearch\n  index "cosmos_archive_{number:02d}"\n  id record_{number:02d}\n  fields {{\n    category keyword values ["Current", "Archived", "Pending"]\n    record_{number:02d} keyword\n  }}\n}}\n'
            return (
                before
                if variant == "mutated"
                else before.replace('values ["Current", "Archived", "Pending"]', "enum(3)", 1)
            )
        before = f'metis {LANGUAGE_VERSION}\ncatalog public.video {{\n  driver opensearch\n  index "{name}"\n  id asset_{number:02d}\n  fields {{\n    asset_{number:02d} keyword\n    state keyword values ["Open", "Closed"]\n  }}\n}}\n'
        return (
            before
            if variant == "mutated"
            else before.replace('values ["Open", "Closed"]', "enum(2)", 1)
        )
    if heldout:
        fixed = f'metis {LANGUAGE_VERSION}\ncatalog public.video {{\n  driver opensearch\n  index "cosmos_market_{number:02d}"\n  id sku_{number:02d}\n  fields {{\n    tags keyword multi enum(4)\n    sku_{number:02d} keyword\n  }}\n}}\n'
        if variant == "mutated":
            return fixed.replace(
                "tags keyword multi enum(4)",
                'tags keyword multi enum(4) values ["north", "south", "east", "west"]',
                1,
            )
        return fixed
    fixed = f'metis {LANGUAGE_VERSION}\ncatalog public.video {{\n  driver opensearch\n  index "{name}"\n  id asset_{number:02d}\n  fields {{\n    asset_{number:02d} keyword\n    labels keyword multi enum(3)\n  }}\n}}\n'
    if variant == "mutated":
        return fixed.replace(
            "labels keyword multi enum(3)",
            'labels keyword multi enum(3) values ["amber", "indigo", "jade"]',
            1,
        )
    return fixed


def _f2_replacement(number: int) -> tuple[str, str]:
    return (
        ('values ["Current", "Archived", "Pending"]', "enum(3)")
        if number >= 32
        else ('values ["Open", "Closed"]', "enum(2)")
    )


def _f3_marker(number: int) -> str:
    return "tags keyword multi enum(4)" if number >= 32 else "labels keyword multi enum(3)"


def _rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # The first 48 training records are the canonicality-targeted tranche.
    for family in ("F-1", "F-2", "F-3"):
        for n in range(16):
            rows.append(
                {
                    "blueprint_id": f"{NAMESPACE}.canonical.{family.lower()}.{n:02d}",
                    "family": family,
                    "split": "train",
                    "kind": "canonicality",
                    "group": f"{NAMESPACE}.train.{family.lower()}.canonical.{n // 4:02d}",
                    "template_root": f"{NAMESPACE}.template.train.{family.lower()}.v1",
                    "number": n,
                    "ordinal": len(rows),
                }
            )
    replay = {"F-1": 6, "F-2": 5, "F-3": 5}
    for family in ("F-1", "F-2", "F-3"):
        for n in range(replay[family]):
            base = 16 + n
            rows.append(
                {
                    "blueprint_id": f"{NAMESPACE}.replay.{family.lower()}.{n:02d}",
                    "family": family,
                    "split": "train",
                    "kind": "replay",
                    "group": f"{NAMESPACE}.train.{family.lower()}.replay.{n // 3:02d}",
                    "template_root": f"{NAMESPACE}.template.train.{family.lower()}.v1",
                    "number": base,
                    "ordinal": len(rows),
                }
            )
    dev = {"F-1": 5, "F-2": 5, "F-3": 6}
    for family in ("F-1", "F-2", "F-3"):
        for n in range(dev[family]):
            rows.append(
                {
                    "blueprint_id": f"{NAMESPACE}.dev.{family.lower()}.{n:02d}",
                    "family": family,
                    "split": "dev",
                    "kind": "heldout",
                    "group": f"{NAMESPACE}.dev.{family.lower()}.{n // 3:02d}",
                    "template_root": f"{NAMESPACE}.template.dev.{family.lower()}.v1",
                    "number": 32 + n,
                    "ordinal": len(rows),
                }
            )
    return rows


def build_blueprint() -> dict[str, Any]:
    rows = _rows()
    body = {
        "schema_version": 1,
        "wave": WAVE,
        "namespace": NAMESPACE,
        "public_synthetic_only": True,
        "metis": {
            "revision": PINNED_REVISION,
            "tree": PINNED_TREE,
            "surface_revision": SURFACE_REVISION,
            "language_version": LANGUAGE_VERSION,
        },
        "counts": COUNTS,
        "max_derivations_per_group": 4,
        "canonicality_train": {"count": 48, "per_family": 16},
        "exclusions": list(EXCLUDED_MARKERS),
        "exclusions_sha256": EXCLUSIONS_SHA256,
        "b12_roster_sha256": B12_ROSTER_SHA256,
        "roster": rows,
    }
    return {**body, "blueprint_sha256": _hash(body)}


def _oracle_ok(result: Any) -> bool:
    return (
        isinstance(result, dict)
        and isinstance(result.get("result"), dict)
        and result["result"].get("status") == "ok"
    )


def _envelope(result: Any, *, phase: str, source: str, expected: str) -> dict[str, Any]:
    return {"phase": phase, "expected": expected, "source_sha256": _hash(source), "result": result}


def _call(source: str, *, snapshot: Any) -> dict[str, Any]:
    try:
        normalized, receipt = _describe_source_in_snapshot(snapshot, source)
    except (
        CatalogMaintenanceProbeError,
        CatalogRetrievalError,
        CatalogRetrievalRefreshError,
    ) as error:
        return {
            "result": {
                "status": "invalid",
                "failure_code": "catalog_domain_rejected",
                "failure_hash": _hash(str(error)),
            }
        }
    catalogs = normalized.get("catalogs") if isinstance(normalized, dict) else None
    if (
        not isinstance(catalogs, list)
        or len(catalogs) != 1
        or not isinstance(catalogs[0], dict)
        or catalogs[0].get("name") != "public.video"
        or not isinstance(receipt, dict)
        or not _is_hash(receipt.get("receipt_sha256"))
    ):
        raise ValueError("catalog describe returned malformed semantic evidence")
    return {"result": {"status": "ok", "normalized": normalized, "receipt": receipt}}


def _prompt_input(row: dict[str, Any], *, diagnostic: str = "") -> tuple[dict[str, Any], str]:
    family, number = row["family"], row["number"]
    before_source: str | None = None
    if family == "F-1":
        request = (
            (
                f"Author exactly catalog public.video with driver opensearch, index "
                f'"cosmos_audio_{number:02d}", id clip_{number:02d}, and a fields block '
                f"containing state keyword enum(4) and clip_{number:02d} keyword. "
            )
            if number >= 32
            else (
                f"Author exactly catalog public.video with driver opensearch, index "
                f'"atlas_1_{number:02d}", id asset_{number:02d}, and a fields block '
                f"containing asset_{number:02d} keyword and state keyword enum(3). "
            )
        )
        request += (
            "The bounded state values stay external. Return only the complete Metis 0.43 source."
        )
    elif family == "F-2":
        before_source = _source(family, number, "mutated")
        _legacy, marker = _f2_replacement(number)
        request = (
            f"Replace exactly the legacy inline domain with {marker}; preserve every other "
            "character. Return only the complete Metis 0.43 source."
        )
    else:
        before_source = _source(family, number, "mutated")
        request = (
            f"Remove only the forbidden inline values that follow {_f3_marker(number)}; "
            "preserve the external marker and every unrelated character. Return "
            "only the complete Metis 0.43 source."
        )
        if not diagnostic:
            raise ValueError("F-3 prompt requires the pinned oracle diagnostic")
        request += "\nOracle diagnostic: " + diagnostic
    inp: dict[str, Any] = {
        "request": request,
        "family": family,
        "blueprint_id": row["blueprint_id"],
    }
    message_user = request
    if before_source is not None:
        inp["before_source"] = before_source
        message_user += "\nCurrent source:\n" + before_source
    if family == "F-3":
        inp["mutated_source"] = before_source
    return inp, message_user


def _example(row: dict[str, Any], *, snapshot: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    family, number = row["family"], row["number"]
    fixed = _source(family, number)
    if family == "F-1":
        source = fixed
        results = [
            (
                "fixed",
                _call(
                    source,
                    snapshot=snapshot,
                ),
            )
        ]
        oracles = ["parse", "link", "validate", "compile", "semantic"]
    elif family == "F-2":
        before, source = _source(family, number, "mutated"), fixed
        legacy, marker = _f2_replacement(number)
        results = [
            (
                "fixed",
                _call(
                    source,
                    snapshot=snapshot,
                ),
            )
        ]
        if source.count(marker) != 1 or before.replace(legacy, marker, 1) != source:
            raise ValueError("F-2 is not an exact single replacement")
        fixed = source
        oracles = ["patch_minimality", "parse", "link", "validate", "compile", "semantic"]
    else:
        before, source = _source(family, number, "mutated"), fixed
        bad = _call(
            before,
            snapshot=snapshot,
        )
        good = _call(
            source,
            snapshot=snapshot,
        )
        if _oracle_ok(bad) or not _oracle_ok(good):
            raise ValueError("F-3 requires mutated oracle failure and fixed oracle pass")
        results = [("mutated", bad), ("fixed", good)]
        oracles = ["diagnostic", "parse", "link", "validate", "compile", "semantic"]
    for phase, result in results:
        if phase == "fixed" and not _oracle_ok(result):
            raise ValueError(f"oracle did not pass for {row['blueprint_id']}")
    diagnostic = ""
    if family == "F-3":
        diagnostic = json.dumps(results[0][1], ensure_ascii=False, sort_keys=True)
    inp, message_user = _prompt_input(row, diagnostic=diagnostic)
    out = {"assistant_content": fixed}
    eid = example_id(1, inp, out)
    parent = _hash(
        {
            "namespace": NAMESPACE,
            "template_root": row["template_root"],
            "group": row["group"],
        }
    )
    evidence = _hash(results[-1][1])
    oracle_records = [
        {"name": name, "applicable": True, "result": "pass", "evidence_hash": evidence}
        for name in oracles
    ]
    example = {
        "schema_version": 1,
        "example_id": eid,
        "task_family": family,
        "input": inp,
        "output": out,
        "messages": [
            {"role": "system", "content": "You produce only valid Metis source."},
            {"role": "user", "content": message_user},
            {"role": "assistant", "content": fixed},
        ],
        "metis": {
            "source_revision": PINNED_REVISION,
            "language_version": LANGUAGE_VERSION,
            "paths": ["public-synthetic"],
        },
        "provenance": {
            "parents": [parent],
            "generator": NAMESPACE,
            "generator_version": "1",
            "leakage_group": row["group"],
        },
        "sensitivity": "public",
        "split": row["split"],
        "positive": True,
        "status": "accepted",
        "oracles": oracle_records,
    }
    provenance = {
        "blueprint": row,
        "example_id": eid,
        "source_sha256": _hash(fixed),
        "oracle_envelopes": [
            _envelope(
                r,
                phase=p,
                source=(fixed if p == "fixed" else _source(family, number, "mutated")),
                expected=("pass" if p == "fixed" else "fail"),
            )
            for p, r in results
        ],
    }
    return example, provenance


def materialize(
    *,
    metis_root: str,
    node_path: str,
    destination: str | os.PathLike[str] = "artifacts/initial-local-qlora-v1/dataset",
) -> dict[str, Any]:
    target = _dataset_target(destination)
    if target.exists() or target.is_symlink():
        raise ValueError("destination must be absent")
    stage = Path(tempfile.mkdtemp(prefix=".dataset-staging-", dir=target.parent))
    try:
        pin_manifest = pin.load_catalog_maintenance_pin()
        if (
            pin_manifest["revision"] != PINNED_REVISION
            or pin_manifest["tree"] != PINNED_TREE
            or pin_manifest["surface_revision"] != SURFACE_REVISION
        ):
            raise ValueError("catalog maintenance pin mismatch")
        blueprint = build_blueprint()
        examples: list[dict[str, Any]] = []
        provenance: list[dict[str, Any]] = []
        with _pinned_snapshot(Path(metis_root), Path(node_path)) as snapshot:
            for row in blueprint["roster"]:
                example, evidence = _example(row, snapshot=snapshot)
                examples.append(example)
                provenance.append(evidence)
        errors = validate_dataset(examples)
        if errors:
            raise ValueError("dataset validation failed: " + "; ".join(errors))
        split = build_split_manifest(examples)
        manifest = dataset_manifest(examples, split_manifest_id=split["split_manifest_id"])

        def write_json(name: str, value: Any) -> str:
            raw = canonical_json_bytes(value) + b"\n"
            _write_fsynced(stage / name, raw)
            return _raw_hash(raw)

        def write_jsonl(name: str, rows: list[dict[str, Any]]) -> str:
            raw = b"".join(
                canonical_json_bytes(item) + b"\n"
                for item in sorted(rows, key=lambda item: item.get("example_id", ""))
            )
            _write_fsynced(stage / name, raw)
            return _raw_hash(raw)

        hashes = {
            "blueprint.json": write_json("blueprint.json", blueprint),
            "provenance.jsonl": write_jsonl("provenance.jsonl", provenance),
            "train.jsonl": write_jsonl(
                "train.jsonl", [item for item in examples if item["split"] == "train"]
            ),
            "dev.jsonl": write_jsonl(
                "dev.jsonl", [item for item in examples if item["split"] == "dev"]
            ),
            "split-manifest.json": write_json("split-manifest.json", split),
            "dataset-manifest.json": write_json("dataset-manifest.json", manifest),
        }
        receipt_body = {
            "schema_version": 1,
            "status": "materialized_verified",
            "wave": WAVE,
            "catalog_pin_sha256": pin.manifest_sha256(pin_manifest),
            "exclusions_sha256": EXCLUSIONS_SHA256,
            "b12_roster_sha256": B12_ROSTER_SHA256,
            "counts": COUNTS,
            "hashes": hashes,
            "split_manifest": split["split_manifest_id"],
            "dataset_manifest": manifest["jsonl_sha256"],
        }
        receipt = {**receipt_body, "receipt_sha256": _hash(receipt_body)}
        write_json("receipt.json", receipt)
        directory = os.open(stage, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        os.replace(stage, target)
        parent = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        return receipt
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def verify(
    destination: str | os.PathLike[str] = "artifacts/initial-local-qlora-v1/dataset",
) -> list[str]:
    try:
        target = _dataset_target(destination)
    except (OSError, ValueError) as error:
        return [str(error)]
    errors: list[str] = []
    required = {
        "blueprint.json",
        "train.jsonl",
        "dev.jsonl",
        "provenance.jsonl",
        "split-manifest.json",
        "dataset-manifest.json",
        "receipt.json",
    }
    if target.is_symlink() or not target.is_dir():
        return ["dataset root must be a regular directory"]
    entries = list(target.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        errors.append("dataset contains a symlink, directory, or special file")
    names = {path.name for path in entries}
    if names != required:
        errors.append(f"dataset file roster mismatch: {sorted(names)}")
    if errors:
        return errors

    def load(text: str, label: str) -> Any:
        if not text.strip():
            raise ValueError(f"{label} is empty")
        return json.loads(
            text,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON value in {label}: {value}")
            ),
        )

    try:
        train = [
            load(line, "train.jsonl")
            for line in (target / "train.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        dev = [
            load(line, "dev.jsonl")
            for line in (target / "dev.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        provenance = [
            load(line, "provenance.jsonl")
            for line in (target / "provenance.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        dataset = load(
            (target / "dataset-manifest.json").read_text(encoding="utf-8"),
            "dataset-manifest.json",
        )
        split = load(
            (target / "split-manifest.json").read_text(encoding="utf-8"),
            "split-manifest.json",
        )
        receipt = load((target / "receipt.json").read_text(encoding="utf-8"), "receipt.json")
        blueprint = load((target / "blueprint.json").read_text(encoding="utf-8"), "blueprint.json")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        return [f"dataset JSON is invalid: {error}"]

    rows = [*train, *dev]
    errors.extend(validate_dataset(rows, dataset))
    errors.extend(validate_split_manifest(rows, split))
    counts = {
        split: {
            family: sum(row["split"] == split and row["task_family"] == family for row in rows)
            for family in ("F-1", "F-2", "F-3")
        }
        for split in ("train", "dev")
    }
    if counts != COUNTS:
        errors.append("exact split/family counts do not match blueprint")
    if len(train) != 64 or len(dev) != 16:
        errors.append("dataset must contain exactly 64 train and 16 dev rows")
    if len(rows) != 80 or len({row.get("example_id") for row in rows}) != 80:
        errors.append("dataset must contain 80 distinct IDs")
    if {row["provenance"]["leakage_group"] for row in rows if row["split"] == "train"} & {
        row["provenance"]["leakage_group"] for row in rows if row["split"] == "dev"
    }:
        errors.append("train/dev leakage groups overlap")
    blueprint_body = {key: value for key, value in blueprint.items() if key != "blueprint_sha256"}
    if blueprint.get("blueprint_sha256") != _hash(blueprint_body):
        errors.append("blueprint identity mismatch")
    if (
        blueprint.get("metis")
        != {
            "revision": PINNED_REVISION,
            "tree": PINNED_TREE,
            "surface_revision": SURFACE_REVISION,
            "language_version": LANGUAGE_VERSION,
        }
        or blueprint.get("exclusions_sha256") != EXCLUSIONS_SHA256
        or blueprint.get("b12_roster_sha256") != B12_ROSTER_SHA256
    ):
        errors.append("blueprint pin or exclusion identity mismatch")
    expected_blueprint = build_blueprint()
    if blueprint != expected_blueprint:
        errors.append("blueprint differs from the deterministic registered roster")

    receipt_body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != _hash(receipt_body):
        errors.append("receipt self-hash mismatch")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "materialized_verified"
        or receipt.get("wave") != WAVE
        or receipt.get("counts") != COUNTS
        or receipt.get("exclusions_sha256") != EXCLUSIONS_SHA256
        or receipt.get("b12_roster_sha256") != B12_ROSTER_SHA256
        or receipt.get("split_manifest") != split.get("split_manifest_id")
        or receipt.get("dataset_manifest") != dataset.get("jsonl_sha256")
    ):
        errors.append("receipt contract fields mismatch")
    try:
        expected_catalog_pin = pin.manifest_sha256(pin.load_catalog_maintenance_pin())
    except (OSError, ValueError, KeyError, TypeError) as error:
        errors.append(f"catalog pin contract cannot be loaded: {error}")
    else:
        if receipt.get("catalog_pin_sha256") != expected_catalog_pin:
            errors.append("receipt catalog pin identity mismatch")
    expected_hashes = {
        name: _file_hash(target / name) for name in required if name != "receipt.json"
    }
    if receipt.get("hashes") != expected_hashes or not all(
        _is_hash(value) for value in expected_hashes.values()
    ):
        errors.append("receipt file hashes mismatch")

    if len(provenance) != 80:
        errors.append("provenance roster is not complete")
    if {item.get("example_id") for item in provenance} != {item.get("example_id") for item in rows}:
        errors.append("provenance/example ID rosters differ")
    for item in provenance:
        envelopes = item.get("oracle_envelopes", [])
        expected = 2 if item.get("blueprint", {}).get("family") == "F-3" else 1
        if len(envelopes) != expected:
            errors.append("oracle envelope roster/status is incomplete")
            continue
        for envelope in envelopes:
            phase = envelope.get("phase")
            expected_status = envelope.get("expected")
            result = envelope.get("result", {}).get("result", {})
            status = result.get("status") if isinstance(result, dict) else None
            valid = (
                phase == "fixed"
                and expected_status == "pass"
                and status == "ok"
                and isinstance(result.get("normalized"), dict)
                and isinstance(result.get("receipt"), dict)
            ) or (
                phase == "mutated"
                and expected_status == "fail"
                and status == "invalid"
                and result.get("failure_code") == "catalog_domain_rejected"
                and _is_hash(result.get("failure_hash"))
            )
            if not valid or not _is_hash(envelope.get("source_sha256")):
                errors.append("oracle envelope roster/status is incomplete")
    try:
        rows_by_id = {item["example_id"]: item for item in rows}
        provenance_by_blueprint = {item["blueprint"]["blueprint_id"]: item for item in provenance}
        if len(rows_by_id) != 80 or len(provenance_by_blueprint) != 80:
            raise ValueError("deterministic dataset/provenance identity is not one-to-one")
        for blueprint_row in expected_blueprint["roster"]:
            record = provenance_by_blueprint[blueprint_row["blueprint_id"]]
            if record.get("blueprint") != blueprint_row:
                raise ValueError("provenance blueprint row drift")
            family, number = blueprint_row["family"], blueprint_row["number"]
            fixed = _source(family, number)
            envelopes = record.get("oracle_envelopes")
            if not isinstance(envelopes, list):
                raise ValueError("oracle evidence list is missing")
            expected_phases = ["mutated", "fixed"] if family == "F-3" else ["fixed"]
            if [item.get("phase") for item in envelopes] != expected_phases:
                raise ValueError("oracle evidence phase order drift")
            for envelope in envelopes:
                phase = envelope["phase"]
                source = fixed if phase == "fixed" else _source(family, number, "mutated")
                if envelope.get("source_sha256") != _hash(source):
                    raise ValueError("oracle evidence source hash drift")
                result = envelope.get("result", {}).get("result")
                if phase == "fixed":
                    if not isinstance(result, dict) or result.get("status") != "ok":
                        raise ValueError("fixed oracle evidence is not successful")
                    describe_receipt = result.get("receipt")
                    if not isinstance(describe_receipt, dict):
                        raise ValueError("describe receipt is missing")
                    describe_body = {
                        key: value
                        for key, value in describe_receipt.items()
                        if key != "receipt_sha256"
                    }
                    if describe_receipt.get("receipt_sha256") != _hash(describe_body):
                        raise ValueError("describe receipt self-hash drift")
                elif (
                    not isinstance(result, dict)
                    or result.get("status") != "invalid"
                    or result.get("failure_code") != "catalog_domain_rejected"
                ):
                    raise ValueError("mutated oracle evidence is not the registered rejection")
            diagnostic = (
                json.dumps(envelopes[0]["result"], ensure_ascii=False, sort_keys=True)
                if family == "F-3"
                else ""
            )
            expected_input, expected_user = _prompt_input(blueprint_row, diagnostic=diagnostic)
            expected_output = {"assistant_content": fixed}
            expected_id = example_id(1, expected_input, expected_output)
            if record.get("example_id") != expected_id or record.get("source_sha256") != _hash(
                fixed
            ):
                raise ValueError("example/source deterministic identity drift")
            example = rows_by_id[expected_id]
            expected_parent = _hash(
                {
                    "namespace": NAMESPACE,
                    "template_root": blueprint_row["template_root"],
                    "group": blueprint_row["group"],
                }
            )
            oracle_names = {
                "F-1": ["parse", "link", "validate", "compile", "semantic"],
                "F-2": [
                    "patch_minimality",
                    "parse",
                    "link",
                    "validate",
                    "compile",
                    "semantic",
                ],
                "F-3": ["diagnostic", "parse", "link", "validate", "compile", "semantic"],
            }[family]
            evidence_hash = _hash(envelopes[-1]["result"])
            expected_oracles = [
                {
                    "name": name,
                    "applicable": True,
                    "result": "pass",
                    "evidence_hash": evidence_hash,
                }
                for name in oracle_names
            ]
            if (
                example.get("input") != expected_input
                or example.get("output") != expected_output
                or example.get("messages")
                != [
                    {"role": "system", "content": "You produce only valid Metis source."},
                    {"role": "user", "content": expected_user},
                    {"role": "assistant", "content": fixed},
                ]
                or example.get("task_family") != family
                or example.get("split") != blueprint_row["split"]
                or example.get("oracles") != expected_oracles
                or example.get("provenance")
                != {
                    "parents": [expected_parent],
                    "generator": NAMESPACE,
                    "generator_version": "1",
                    "leakage_group": blueprint_row["group"],
                }
            ):
                raise ValueError("deterministic example content or evidence cross-link drift")
    except (KeyError, TypeError, ValueError) as error:
        errors.append(f"deterministic dataset reconstruction failed: {error}")
    roster = blueprint.get("roster", [])
    if [x.get("kind") for x in roster[:48]] != ["canonicality"] * 48 or [
        x.get("kind") for x in roster[48:64]
    ] != ["replay"] * 16:
        errors.append("blueprint tranche order mismatch")
    if any(
        sum(row["provenance"]["leakage_group"] == group for row in rows) > 4
        for group in {row["provenance"]["leakage_group"] for row in rows}
    ):
        errors.append("derivation group exceeds four records")
    train_roots = {
        item.get("template_root")
        for item in roster
        if isinstance(item, dict) and item.get("split") == "train"
    }
    dev_roots = {
        item.get("template_root")
        for item in roster
        if isinstance(item, dict) and item.get("split") == "dev"
    }
    if (
        len(train_roots) != 3
        or len(dev_roots) != 3
        or None in train_roots | dev_roots
        or train_roots & dev_roots
    ):
        errors.append("train/dev template roots are not genuinely disjoint")
    try:
        if _file_hash(B12_ROSTER) != B12_ROSTER_SHA256:
            raise ValueError("frozen B12 roster file hash drift")
        b12 = load(B12_ROSTER.read_text(encoding="utf-8"), "B12 roster")
        b12_tasks = b12.get("tasks") if isinstance(b12, dict) else None
        if not isinstance(b12_tasks, list) or len(b12_tasks) != 12:
            raise ValueError("frozen B12 roster denominator drift")
        b12_groups = {
            task.get("parent_template_group") for task in b12_tasks if isinstance(task, dict)
        }
        dataset_groups = {row["provenance"]["leakage_group"] for row in rows}
        if len(b12_groups) != 12 or None in b12_groups or dataset_groups & b12_groups:
            raise ValueError("dataset/B12 leakage groups overlap or are incomplete")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"frozen B12 genealogy verification failed: {error}")
    if any(" values [" in row.get("messages", [{}])[-1].get("content", "") for row in rows):
        errors.append("adapter targets contain inline catalog values")
    forbidden = (
        "author-audience-enum5",
        "author-summary-open",
        "author-availability-inline",
        "author-nested-code-enum4",
        "root/successor-",
        "template/successor-",
        "w5xs-",
        "bridge-f",
    )
    serialized = json.dumps({"rows": rows, "provenance": provenance}, sort_keys=True)
    if any(marker in serialized for marker in forbidden):
        errors.append("dataset contains a forbidden held-out lineage marker")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("blueprint")
    b.add_argument("--output", type=Path)
    m = sub.add_parser("materialize")
    m.add_argument("--metis-root", required=True)
    m.add_argument("--node-path", required=True)
    m.add_argument("--destination", default="artifacts/initial-local-qlora-v1/dataset")
    v = sub.add_parser("verify")
    v.add_argument("--destination", default="artifacts/initial-local-qlora-v1/dataset")
    args = parser.parse_args(argv)
    if args.command == "blueprint":
        data = canonical_json_bytes(build_blueprint()) + b"\n"
        args.output.write_bytes(data) if args.output else print(data.decode(), end="")
    elif args.command == "materialize":
        print(
            json.dumps(
                materialize(
                    metis_root=args.metis_root,
                    node_path=args.node_path,
                    destination=args.destination,
                ),
                sort_keys=True,
            )
        )
    else:
        errors = verify(args.destination)
        print(json.dumps({"ok": not errors, "errors": errors}, sort_keys=True))
        return int(bool(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
