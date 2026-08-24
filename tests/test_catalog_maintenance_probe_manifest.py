from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "manifests/catalog-maintenance-probe-v1.json"
SCHEMA_PATH = ROOT / "schemas/catalog-maintenance-probe.schema.json"
FIXTURE_ROOT = ROOT / "fixtures/catalog-maintenance/probe-v1"
UPSTREAM = {
    "revision": "5e112f9148f40e7e792052e896c5a9efe8eaf0a2",
    "tree": "41c7a2b6890fa42d8123bd93f6560d0b9bfae8af",
    "language_version": "0.43",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_catalog_probe_manifest_and_case_files_are_strictly_bound() -> None:
    manifest = _load(MANIFEST_PATH)
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest), key=lambda item: list(item.path)
    )
    assert errors == [], [error.message for error in errors]

    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    assert manifest["manifest_sha256"] == _hash_bytes(_canonical(body))

    expected_paths = {Path(item["path"]).as_posix() for item in manifest["files"]}
    actual_paths = {
        path.relative_to(ROOT).as_posix() for path in FIXTURE_ROOT.rglob("*") if path.is_file()
    }
    assert actual_paths == expected_paths

    case_validator = Draft202012Validator(schema["$defs"]["case"])
    cases_by_id: dict[str, dict[str, Any]] = {}
    for record in manifest["files"]:
        path = ROOT / record["path"]
        raw = path.read_bytes()
        assert len(raw) == record["bytes"]
        assert _hash_bytes(raw) == record["sha256"]
        case = _load(path)
        case_errors = sorted(case_validator.iter_errors(case), key=lambda item: list(item.path))
        assert case_errors == [], [error.message for error in case_errors]
        assert case["case_id"] not in cases_by_id
        cases_by_id[case["case_id"]] = case

    assert set(cases_by_id) == {item["case_id"] for item in manifest["cases"]}
    roots: set[str] = set()
    templates: set[str] = set()
    for binding in manifest["cases"]:
        case = cases_by_id[binding["case_id"]]
        assert case["family"] == binding["family"]
        assert case["mode"] == binding["mode"]
        assert case["construct"] == binding["construct"]
        assert case["difficulty"] == binding["difficulty"]
        assert case["provenance"]["semantic_root"] == binding["root_id"]
        assert case["provenance"]["template_id"] == binding["template_id"]
        assert binding["fixture_path"] in expected_paths
        assert case["upstream"] == UPSTREAM
        roots.add(binding["root_id"])
        templates.add(binding["template_id"])
        target = case["target"]
        for fragment in target["required_fragments"]:
            assert fragment in target["expected_source"], (case["case_id"], fragment)
        for fragment in target["forbidden_fragments"]:
            assert fragment not in target["expected_source"], (case["case_id"], fragment)
        assert case["oracle"]["status"] == "pending_execution"
        assert case["oracle"]["model_outputs_observed"] is False

    assert len(roots) == len(templates) == 8
    assert {case["provenance"]["lineage_component"] for case in cases_by_id.values()} == {
        "public-synthetic-catalog-v1"
    }
    assert [binding["family"] for binding in manifest["cases"]].count("F-1") == 5
    assert [binding["family"] for binding in manifest["cases"]].count("F-2") == 2
    assert [binding["family"] for binding in manifest["cases"]].count("F-3") == 1


def test_catalog_probe_has_exact_pre_output_gate_and_retrieval_boundary() -> None:
    manifest = _load(MANIFEST_PATH)
    assert manifest["status"] == "static_pre_output_specification"
    assert manifest["authority_scope"] == "public_synthetic_only"
    assert manifest["upstream"] == {"repository": "ares-matioska/metis", **UPSTREAM}
    assert manifest["model"] == {
        "family": "Qwen3.8",
        "adapter_enabled": False,
        "temperature": 0,
        "seed": 17,
        "max_tokens": 512,
        "max_repair_cycles": 2,
    }
    assert manifest["gates"] == {
        "required_case_passes": "8/8",
        "critical_failures_max": 0,
        "invented_values_max": 0,
        "legacy_inline_for_enum_or_open_max": 0,
        "retrieval_errors_max": 0,
        "model_outputs_before_seal": False,
        "accuracy_claim": False,
        "promotion_claim": False,
        "training_authority": False,
    }
    assert manifest["nonclaims"] == [
        "no_accuracy_claim",
        "no_promotion_claim",
        "no_training_authority",
        "no_tenant_dataset_authority",
        "no_independent_accuracy_denominator",
        "no_live_execution_attestation",
        "nonpromotable",
    ]

    cases = [_load(ROOT / item["fixture_path"]) for item in manifest["cases"]]
    boundary = next(case for case in cases if case["case_id"] == "author-retrieval-curated")
    assert boundary["retrieval"] == {
        "kind": "public_synthetic_value",
        "query": {"operation": "values", "catalog": "video", "field": "genre"},
        "expected": {
            "kind": "enum",
            "size": 1,
            "nature": "editorial",
            "value": "Curated",
            "source_receipt_query": "values-enum-editorial",
        },
    }
    assert "Curated" not in boundary["target"]["expected_source"]
    assert all(case["oracle"]["status"] == "pending_execution" for case in cases)
    assert all(case["oracle"]["model_outputs_observed"] is False for case in cases)
    assert all(
        case["retrieval"]
        == {"kind": "not_required", "query": None, "expected": {"values_in_model_input": False}}
        for case in cases
        if case["case_id"] != "author-retrieval-curated"
    )
