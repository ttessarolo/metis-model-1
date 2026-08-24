from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest

from metis_model1 import oracles

PROJECT_ROOT = Path(__file__).parents[1]
TOOL_PATH = PROJECT_ROOT / "runtime/w3_native_evidence.py"


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("w3_native_evidence_under_test", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _rehash(value: dict) -> None:
    source = value["source_closure"]
    source["counts"]["files"] = len(source["rows"])
    source["counts"]["bytes"] = sum(row["size"] for row in source["rows"])
    source["counts"]["edges"] = sum(len(row["imports"]) for row in source["rows"])
    source["counts"]["relative_resolutions"] = sum(
        edge["resolved_path"] is not None for row in source["rows"] for edge in row["imports"]
    )
    source["roster_sha256"] = _hash(source["rows"])

    package = value["package_closure"]
    package["counts"]["files"] = len(package["rows"])
    package["counts"]["bytes"] = sum(row["size"] for row in package["rows"])
    package["counts"]["packages"] = len({row["package"] for row in package["rows"]})
    package["package_identities"] = sorted({row["package"] for row in package["rows"]})
    package["roster_sha256"] = _hash(package["rows"])

    capsule = value["capsule_closure"]
    capsule["counts"]["files"] = len(capsule["rows"])
    capsule["counts"]["bytes"] = sum(row["size"] for row in capsule["rows"])
    capsule["roster_sha256"] = _hash(capsule["rows"])
    value["manifest_sha256"] = _hash(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )


def _mutated_manifest(module: ModuleType, attack: str) -> dict:
    value = deepcopy(module.load_evidence_manifest())
    if attack == "missing-row":
        value["source_closure"]["rows"].pop()
    elif attack == "extra-row":
        row = deepcopy(value["source_closure"]["rows"][-1])
        row["path"] = "src/l66-unregistered-extra.ts"
        row["git_blob_oid"] = "0" * 40
        value["source_closure"]["rows"].append(row)
    elif attack == "reordered-row":
        value["source_closure"]["rows"].reverse()
    elif attack == "size-drift":
        value["source_closure"]["rows"][0]["size"] += 1
    elif attack == "mode-drift":
        value["source_closure"]["rows"][0]["mode"] = 0o555
    elif attack == "hash-drift":
        value["source_closure"]["rows"][0]["sha256"] = "sha256:" + "f" * 64
    elif attack == "count-drift":
        _rehash(value)
        value["source_closure"]["counts"]["edges"] += 1
        value["manifest_sha256"] = _hash(
            {key: item for key, item in value.items() if key != "manifest_sha256"}
        )
        return value
    elif attack == "source-entry-drift":
        value["source_closure"]["entries"].pop()
    elif attack == "missing-package-row":
        value["package_closure"]["rows"].pop()
    elif attack == "package-identity-drift":
        value["package_closure"]["rows"][0]["package"] = "unregistered@0.0.0"
    elif attack == "capsule-role-drift":
        value["capsule_closure"]["rows"][0]["role"] = "loader"
    elif attack == "parity-available":
        value["parity"]["available"] = True
    elif attack == "parity-durable-row":
        value["parity"]["durable_rows"] = 1
    elif attack == "console-observation-injection":
        value["parity"]["console_only_observations_included"] = True
    elif attack in {
        "parser-pin",
        "generator-pin",
        "node-pin",
        "loader-pin",
        "runner-pin",
    }:
        name = attack.removesuffix("-pin")
        value["toolchain"][name]["sha256"] = "sha256:" + "c" * 64
    elif attack == "policy-pin":
        value["toolchain"]["policies"]["combined_sha256"] = "sha256:" + "b" * 64
    else:  # pragma: no cover - the parameter roster below is closed.
        raise AssertionError(f"unregistered attack {attack}")
    _rehash(value)
    return value


@pytest.mark.parametrize(
    "attack",
    [
        "missing-row",
        "extra-row",
        "reordered-row",
        "size-drift",
        "mode-drift",
        "hash-drift",
        "count-drift",
        "source-entry-drift",
        "missing-package-row",
        "package-identity-drift",
        "capsule-role-drift",
        "parity-available",
        "parity-durable-row",
        "console-observation-injection",
        "parser-pin",
        "generator-pin",
        "node-pin",
        "loader-pin",
        "runner-pin",
        "policy-pin",
    ],
)
def test_l66_native_evidence_mutations_fail_closed(attack: str) -> None:
    module = _load_tool()
    changed = _mutated_manifest(module, attack)
    with pytest.raises(module.EvidenceError):
        module.verify_evidence_document(changed)


def test_l66_native_evidence_emissions_are_byte_identical_and_independently_verified(
    tmp_path: Path,
) -> None:
    module = _load_tool()
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    module.emit_evidence(first)
    module.emit_evidence(second)
    assert first.read_bytes() == second.read_bytes()
    registered = PROJECT_ROOT / "manifests/w3-native-loader-evidence.json"
    assert first.read_bytes() == registered.read_bytes()
    module.verify_evidence(first)


def test_l67_blocked_emit_and_verify_never_execute_node_tsx_runner_or_canary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_tool()
    observed: list[tuple[str, ...]] = []
    original_run = module._run

    def git_only(command: list[str], *args: object, **kwargs: object) -> bytes:
        rendered = tuple(str(item) for item in command)
        observed.append(rendered)
        assert rendered[0] == "git", f"blocked receipt launched a non-Git process: {rendered}"
        return original_run(command, *args, **kwargs)

    def forbidden_capture(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("blocked receipt reopened parity capture")

    monkeypatch.setattr(module, "_run", git_only)
    monkeypatch.setattr(module, "_capture_parity", forbidden_capture)
    emitted = tmp_path / "blocked.json"
    module.emit_evidence(emitted)
    module.verify_evidence(emitted)
    assert observed
    assert all(command[0] == "git" for command in observed)


@pytest.mark.parametrize(
    ("clause", "type_only"),
    [
        (
            """import {
                // Inline comments previously escaped the regex census.
                value,
                type Shape,
            } from './dependency.js';
            """,
            False,
        ),
        (
            """import {
                /* A multiline comment is legal inside named imports. */
                type Shape,
                type Other,
            } from './dependency.js';
            """,
            True,
        ),
    ],
)
def test_l67_process_free_typescript_import_census_handles_multiline_comments(
    clause: str, type_only: bool
) -> None:
    module = _load_tool()
    assert module._parse_typescript_imports(
        "tooling/src/example.ts",
        (clause + "\nexport const value = 1;\n").encode(),
        {"tooling/src/example.ts", "tooling/src/dependency.ts"},
    ) == [
        {
            "dynamic": False,
            "resolved_path": "tooling/src/dependency.ts",
            "specifier": "./dependency.js",
            "type_only": type_only,
        }
    ]


def test_l66_native_evidence_is_metadata_only_and_states_exact_nonclaims() -> None:
    module = _load_tool()
    value = module.load_evidence_manifest()
    rendered = _canonical(value)
    assert all(
        forbidden not in rendered
        for forbidden in (b'"source_text"', b'"package_bytes"', b'"payload"', b'"model_weights"')
    )
    assert value["assumptions"] == {
        "exclusive_host_required": True,
        "executed_preimage_authority": False,
    }
    assert value["non_claims"] == [
        "executed_preimage_authority=false",
        "no-durable-parity-evidence",
        "no-production-evidence",
        "no-dataset-qualification",
        "no-training-readiness",
        "no-semantic-accuracy-evidence",
    ]


def test_l66_trace_is_loader_local_and_only_records_sealed_urls() -> None:
    loader = (PROJECT_ROOT / "runtime/metis_oracle/native_ts_loader.mjs").read_text(
        encoding="utf-8"
    )
    assert 'const TRACE_FD_ENV = "METIS_MODEL1_NATIVE_TRACE_FD"' in loader
    assert "const sealedUrl = await rosteredFileUrl" in loader
    assert "writeSync(TRACE_FD, `${JSON.stringify(sealedUrl)}\\n`)" in loader
    assert "METIS_MODEL1_NATIVE_LOADER_URL" not in loader


def test_l66_production_capsule_environments_cannot_enable_reference_trace() -> None:
    module = _load_tool()
    qualifier = module._load_module(PROJECT_ROOT / "runtime/w3_qualifier.py", "l66_trace_qualifier")
    assert oracles.NATIVE_TRACE_FD_ENV == "METIS_MODEL1_NATIVE_TRACE_FD"
    assert oracles.NATIVE_TRACE_FD_ENV not in oracles._capsule_production_environment()
    assert qualifier.V3_NATIVE_TRACE_FD_ENV == oracles.NATIVE_TRACE_FD_ENV
    assert qualifier.V3_NATIVE_TRACE_FD_ENV not in qualifier._v3_capsule_process_environment(
        Path("/private/tmp/l66-production-process-root")
    )
    census = (PROJECT_ROOT / "runtime/metis_oracle/native_evidence_census.mjs").read_text(
        encoding="utf-8"
    )
    assert "METIS_MODEL1_NATIVE_TRACE_FD" not in census
    assert "export async function resolve" not in census
    assert "export async function load" not in census


def test_l66_reference_temp_roster_is_bounded_hashed_and_cleaned(tmp_path: Path) -> None:
    module = _load_tool()
    reference_tmp = tmp_path / "reference-tmp"
    nested = reference_tmp / "tsx-reference"
    nested.mkdir(parents=True)
    (nested / "metadata.bin").write_bytes(b"reference-only")
    receipt = module._snapshot_reference_temp(reference_tmp)
    expected_rows = [
        {
            "kind": "directory",
            "mode": 0o755,
            "path": "tsx-reference",
            "size": 0,
        },
        {
            "kind": "file",
            "mode": 0o644,
            "path": "tsx-reference/metadata.bin",
            "sha256": module._hash_bytes(b"reference-only"),
            "size": len(b"reference-only"),
        },
    ]
    assert receipt == {
        "bytes": len(b"reference-only"),
        "directories": 1,
        "files": 1,
        "reference_only": True,
        "roster_sha256": module._hash(expected_rows),
        "rows": expected_rows,
    }
    cleanup = module._cleanup_reference_temp(reference_tmp, receipt)
    assert cleanup == {
        "attempted": True,
        "deleted_directories": 1,
        "deleted_files": 1,
        "residual_entries": 0,
    }
    assert list(reference_tmp.iterdir()) == []


def test_l66_reference_temp_roster_rejects_symlink(tmp_path: Path) -> None:
    module = _load_tool()
    reference_tmp = tmp_path / "reference-tmp"
    reference_tmp.mkdir()
    (reference_tmp / "escape").symlink_to(tmp_path)
    with pytest.raises(module.EvidenceError, match="symlink"):
        module._snapshot_reference_temp(reference_tmp)


def test_l66_synthetic_comparator_temp_exceeding_bound_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_tool()
    reference_tmp = tmp_path.resolve() / "reference-tmp"
    reference_tmp.mkdir()
    (reference_tmp / "oversized.bin").write_bytes(b"12")
    monkeypatch.setattr(module, "REFERENCE_TEMP_MAX_FILE_BYTES", 1)
    with pytest.raises(module.EvidenceError, match="bounds"):
        module._snapshot_reference_temp(reference_tmp)


def test_l66_capture_is_permanently_closed_after_denominator_stop(tmp_path: Path) -> None:
    module = _load_tool()
    with pytest.raises(module.EvidenceError, match="permanently closed"):
        module.capture_evidence(tmp_path / "forbidden.json")
    assert list(tmp_path.iterdir()) == []
