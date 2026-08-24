from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests/catalog-maintenance-successor-probe-v1.json"
SCHEMA = ROOT / "schemas/catalog-maintenance-successor-probe.schema.json"
CASES_ROOT = ROOT / "fixtures/catalog-maintenance/successor-v1/cases"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def _manifest() -> dict[str, Any]:
    return _load_json(MANIFEST)


def _cases(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    cases = manifest.get("cases")
    assert isinstance(cases, list)
    assert all(isinstance(case, dict) for case in cases)
    return cases


def _case_path(case: dict[str, Any]) -> Path:
    fixture_path = case.get("fixture_path")
    assert isinstance(fixture_path, str)
    path = ROOT / fixture_path
    assert path.is_file(), path
    return path


def _expected_source(case: dict[str, Any]) -> str:
    target = case.get("target")
    if isinstance(target, dict) and isinstance(target.get("expected_source"), str):
        return target["expected_source"]
    expected = case.get("expected_source")
    assert isinstance(expected, str), case.get("case_id")
    return expected


def _context_text(case: dict[str, Any]) -> str:
    prompt = case.get("prompt")
    assert isinstance(prompt, dict), case.get("case_id")
    pieces: list[str] = []
    for key in ("request", "before_source", "retrieved_context", "retrieved_value"):
        value = prompt.get(key)
        if value is not None:
            pieces.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    for key in ("retrieved_context", "retrieved_value"):
        value = case.get(key)
        if value is not None:
            pieces.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return "\n".join(pieces)


def test_successor_manifest_validates_against_its_schema_and_self_hash() -> None:
    manifest = _manifest()
    schema = _load_json(SCHEMA)
    errors = sorted(error.message for error in Draft202012Validator(schema).iter_errors(manifest))
    assert errors == []
    manifest_hash = manifest.get("manifest_sha256")
    assert isinstance(manifest_hash, str) and manifest_hash.startswith("sha256:")
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    assert manifest_hash == _sha_bytes(_canonical(body))


def test_successor_manifest_binds_exact_raw_files_and_directory_census() -> None:
    manifest = _manifest()
    records = manifest.get("files")
    assert isinstance(records, list)
    expected_paths = {record["path"] for record in records}
    assert all(isinstance(path, str) for path in expected_paths)
    observed_paths = {
        path.relative_to(ROOT).as_posix() for path in CASES_ROOT.glob("*.json") if path.is_file()
    }
    case_paths = {case["fixture_path"] for case in _cases(manifest)}
    assert observed_paths == case_paths
    assert case_paths <= expected_paths
    for record in records:
        path = ROOT / record["path"]
        raw = path.read_bytes()
        assert record["bytes"] == len(raw), record["path"]
        assert record["sha256"] == _sha_bytes(raw), record["path"]


def test_successor_roster_is_eight_distinct_cases_with_expected_modes() -> None:
    manifest = _manifest()
    cases = _cases(manifest)
    assert len(cases) == 8
    for key in ("case_id", "root_id", "template_id"):
        values = [case.get(key) for case in cases]
        assert all(isinstance(value, str) and value for value in values)
        assert len(set(values)) == 8
    assert {case.get("mode") for case in cases} == {"author", "edit", "repair"}
    assert sum(case.get("mode") == "author" for case in cases) == 4
    assert sum(case.get("mode") == "edit" for case in cases) == 3
    assert sum(case.get("mode") == "repair" for case in cases) == 1
    assert manifest.get("counts", {}).get("cases") == 8
    assert manifest.get("counts", {}).get("distinct_roots") == 8
    assert manifest.get("counts", {}).get("distinct_templates") == 8
    assert manifest.get("counts", {}).get("gaps") == 0
    assert all("successor" in str(case.get("root_id")) for case in cases)
    lineage_components = {
        _load_json(_case_path(case)).get("provenance", {}).get("lineage_component")
        for case in cases
    }
    assert len(lineage_components) == 1
    assert "public-synthetic" in str(next(iter(lineage_components)))


def test_successor_sources_are_canonical_and_targets_are_not_in_context() -> None:
    manifest = _manifest()
    for case in _cases(manifest):
        fixture = _load_json(_case_path(case))
        source = _expected_source(fixture)
        assert source.startswith("metis 0.43\n"), case.get("case_id")
        context = _context_text(fixture)
        assert source not in context, case.get("case_id")


def test_successor_cases_have_no_duplicate_fixture_or_target_hashes() -> None:
    manifest = _manifest()
    cases = _cases(manifest)
    fixture_hashes = [_sha_bytes(_case_path(case).read_bytes()) for case in cases]
    assert len(set(fixture_hashes)) == 8
    target_hashes = [
        _sha_bytes(_canonical(_expected_source(_load_json(_case_path(case))))) for case in cases
    ]
    assert len(set(target_hashes)) == 8
