from __future__ import annotations

from pathlib import Path

import pytest

from metis_model1.catalog_maintenance_probe import (
    CatalogMaintenanceProbeError,
    _extract_source,
    _python_runtime_identity,
    _safe_checkpoint_weight_name,
    _worker_sandbox_policy,
    build_prompt,
    canonical_hash,
    gate_arithmetic,
    load_probe_contract,
    score_candidate,
)

ROOT = Path(__file__).resolve().parents[1]


def test_probe_manifest_and_cases_are_eight_distinct_sealed_inputs() -> None:
    manifest, _schema, cases = load_probe_contract()
    assert manifest["counts"] == {
        "cases": 8,
        "distinct_roots": 8,
        "distinct_templates": 8,
        "source_lineages": 1,
        "authors": 5,
        "edits": 2,
        "repairs": 1,
    }
    assert len({case["case_id"] for case in cases}) == 8
    assert all(case["status"] == "sealed_pre_output_spec" for case in cases)


def test_prompt_does_not_contain_expected_source_or_required_target_fragment() -> None:
    _manifest, _schema, cases = load_probe_contract()
    for case in cases:
        retrieval = (
            {"value": "Curated", "size": 1}
            if case["case_id"] == "author-retrieval-curated"
            else None
        )
        prompt = build_prompt(case, retrieval)
        assert case["target"]["expected_source"].strip() not in prompt


def test_curated_retrieval_is_explicit_but_not_target_source() -> None:
    _manifest, _schema, cases = load_probe_contract()
    case = next(case for case in cases if case["case_id"] == "author-retrieval-curated")
    prompt = build_prompt(case, {"value": "Curated", "size": 1})
    assert "Curated" in prompt
    assert "values [" not in prompt


def test_scoring_requires_exact_skeleton_and_rejects_legacy_inline() -> None:
    _manifest, _schema, cases = load_probe_contract()
    case = next(case for case in cases if case["case_id"] == "author-enum3")
    skeleton = {"catalogs": [{"name": "public.video", "fields": []}]}
    good = score_candidate(
        case, "metis 0.43\ngenre keyword enum(3)\n", skeleton, expected_skeleton=skeleton
    )
    assert good["semantic_correct"] == 1
    bad_source = 'metis 0.43\ngenre keyword values ["one"]\n'
    bad = score_candidate(case, bad_source, skeleton, expected_skeleton={"different": True})
    assert bad["semantic_correct"] == 0
    assert bad["legacy_inline"] == 1
    assert bad["invented_values"] == 1


def test_scoring_counts_unlisted_inline_values_as_invention() -> None:
    _manifest, _schema, cases = load_probe_contract()
    case = next(case for case in cases if case["case_id"] == "author-open")
    score = score_candidate(
        case,
        'metis 0.43\ngenre keyword open\nvalues["invented"]\n',
        {"catalogs": []},
        expected_skeleton={"different": True},
    )
    assert score["invented_values"] == 1


def test_tiny_inline_values_are_not_counted_as_invention() -> None:
    _manifest, _schema, cases = load_probe_contract()
    case = next(case for case in cases if case["case_id"] == "author-inline-tiny")
    score = score_candidate(
        case,
        'metis 0.43\ngenre keyword values ["Tiny"]\n',
        {"catalogs": []},
        expected_skeleton={"different": True},
    )
    assert score["invented_values"] == 0


def test_gate_arithmetic_is_fail_closed_and_never_authorizes_training() -> None:
    _manifest, _schema, cases = load_probe_contract()
    passing = [
        {
            "case_id": case["case_id"],
            "root_id": case["provenance"]["semantic_root"],
            "semantic_correct": 1,
            "critical_failure": 0,
            "invented_values": 0,
            "legacy_inline": 0,
            "retrieval_error": 0,
        }
        for case in cases
    ]
    decision = gate_arithmetic(passing)
    assert decision["verdict"] == "NO_RETRAIN"
    assert decision["training_authorized"] is False
    failing = [
        *passing[:7],
        {
            "case_id": cases[7]["case_id"],
            "root_id": cases[7]["provenance"]["semantic_root"],
            "semantic_correct": 0,
            "critical_failure": 0,
            "invented_values": 1,
            "legacy_inline": 1,
            "retrieval_error": 0,
        },
    ]
    assert gate_arithmetic(failing)["verdict"] == "DIAGNOSE"


def test_gate_arithmetic_rejects_duplicate_case_ids() -> None:
    with pytest.raises(CatalogMaintenanceProbeError, match="duplicate case IDs"):
        gate_arithmetic(
            [
                {
                    "case_id": "same",
                    "root_id": "root-a",
                    "semantic_correct": 1,
                    "critical_failure": 0,
                    "invented_values": 0,
                    "legacy_inline": 0,
                    "retrieval_error": 0,
                },
                {
                    "case_id": "same",
                    "root_id": "root-b",
                    "semantic_correct": 1,
                    "critical_failure": 0,
                    "invented_values": 0,
                    "legacy_inline": 0,
                    "retrieval_error": 0,
                },
            ]
        )


def test_gate_arithmetic_rejects_an_arbitrary_eight_case_roster() -> None:
    observations = [
        {
            "case_id": f"arbitrary-{index}",
            "root_id": f"root-{index}",
            "semantic_correct": 1,
            "critical_failure": 0,
            "invented_values": 0,
            "legacy_inline": 0,
            "retrieval_error": 0,
        }
        for index in range(8)
    ]
    assert gate_arithmetic(observations)["verdict"] == "DIAGNOSE"


def test_source_extraction_rejects_text_outside_a_single_fence() -> None:
    source, error = _extract_source("```metis\nmetis 0.43\n```\nextra")
    assert source is None
    assert error == "text_outside_code_fence"


def test_source_extraction_accepts_plain_source_without_wrapper_text() -> None:
    source, error = _extract_source("metis 0.43\ncatalog public.video {\n}\n")
    assert source == "metis 0.43\ncatalog public.video {\n}\n"
    assert error is None


@pytest.mark.parametrize("value", ["../outside.safetensors", "/tmp/outside", "a/b"])
def test_checkpoint_weight_paths_must_be_direct_children(value: str) -> None:
    with pytest.raises(CatalogMaintenanceProbeError, match="escapes the checkpoint"):
        _safe_checkpoint_weight_name(value)


def test_worker_sandbox_denies_network_cache_reads_and_checkpoint_writes() -> None:
    policy = _worker_sandbox_policy(ROOT / "artifacts/w4/2026-08-20-qualification/checkpoint")
    assert "(deny network*)" in policy
    assert "(deny file-write*" in policy
    assert "(deny file-read*" in policy
    assert 'checkpoint/.cache"' in policy


def test_worker_python_identity_preserves_qualification_virtualenv() -> None:
    identity = _python_runtime_identity(ROOT / "qualification/.venv/bin/python")
    assert identity["invocation_path"].endswith("qualification/.venv/bin/python")
    assert identity["sys_prefix"].endswith("qualification/.venv")
    assert identity["python_version"] == "3.12.10"
    assert identity["mlx"] == "0.32.1"
    assert identity["mlx_vlm"] == "0.6.15"


def test_freeze_seal_tamper_is_detectable() -> None:
    body = {"schema_version": 1, "status": "frozen_before_model_output", "tasks": []}
    sealed = {**body, "freeze_sha256": canonical_hash(body)}
    assert sealed["freeze_sha256"] == canonical_hash(
        {key: value for key, value in sealed.items() if key != "freeze_sha256"}
    )
    sealed["tasks"].append({"case_id": "tampered"})
    assert sealed["freeze_sha256"] != canonical_hash(
        {key: value for key, value in sealed.items() if key != "freeze_sha256"}
    )


def test_load_contract_rejects_case_hash_tamper(monkeypatch: pytest.MonkeyPatch) -> None:
    import metis_model1.catalog_maintenance_probe as probe

    original = probe._load_json
    calls = {"count": 0}

    def tamper(path, label, **kwargs):
        value, raw = original(path, label, **kwargs)
        if label.startswith("case ") and calls["count"] == 0:
            calls["count"] += 1
            return value, raw + b"x"
        return value, raw

    monkeypatch.setattr(probe, "_load_json", tamper)
    with pytest.raises(CatalogMaintenanceProbeError, match="case hash drift"):
        load_probe_contract()
