from __future__ import annotations

import json
from pathlib import Path

import pytest

from metis_model1.catalog_maintenance_probe_evidence import (
    DEFAULT_DECISION,
    DEFAULT_EVALUATION,
    EvidenceError,
    build_decision,
    build_evaluation_receipt,
    canonical_hash,
    validate_decision,
    validate_evaluation_receipt,
)

ROOT = Path(__file__).resolve().parents[1]


def test_current_run_projects_to_redacted_receipt() -> None:
    receipt = build_evaluation_receipt()
    assert receipt == json.loads(DEFAULT_EVALUATION.read_text())
    assert receipt["counts"]["semantic_correct"] == 2
    assert receipt["veto_counts"] == {
        "critical_failure": 6,
        "invented_values": 0,
        "legacy_inline": 0,
        "retrieval_error": 6,
    }
    assert receipt["roster"]["cases_distinct"] == 8
    assert not _contains_key(receipt, "text")
    assert validate_evaluation_receipt(receipt) == []


def test_decision_is_diagnostic_only_and_not_qlora_eligible() -> None:
    receipt = json.loads(DEFAULT_EVALUATION.read_text())
    decision = build_decision(receipt)
    assert decision == json.loads(DEFAULT_DECISION.read_text())
    assert decision["status"] == "DIAGNOSE"
    assert decision["delta_qlora"] == {
        "eligible": False,
        "compatible_failures": 0,
        "distinct_roots": 0,
        "reason": "all observed failures are critical or retrieval failures",
    }
    assert decision["training_authorized"] is False
    assert decision["auto_qlora_authorized"] is False
    assert decision["promotion_claim"] is False
    assert decision["accuracy_claim"] is False
    assert validate_decision(decision) == []


def test_tracked_evidence_validates_without_raw_artifacts() -> None:
    evaluation = json.loads(DEFAULT_EVALUATION.read_text())
    decision = json.loads(DEFAULT_DECISION.read_text())
    assert validate_evaluation_receipt(evaluation) == []
    assert validate_decision(decision) == []


def test_self_hash_tamper_is_rejected() -> None:
    evaluation = json.loads(DEFAULT_EVALUATION.read_text())
    evaluation["counts"]["semantic_correct"] = 8
    assert any("self-hash" in error for error in validate_evaluation_receipt(evaluation))


def test_rehashed_roster_and_decision_laundering_are_rejected() -> None:
    evaluation = json.loads(DEFAULT_EVALUATION.read_text())
    evaluation["roster"]["cases"][1] = evaluation["roster"]["cases"][0]
    evaluation["evaluation_sha256"] = canonical_hash(
        {key: value for key, value in evaluation.items() if key != "evaluation_sha256"}
    )
    errors = validate_evaluation_receipt(evaluation)
    assert any("roster" in error or "distinct" in error for error in errors)

    decision = json.loads(DEFAULT_DECISION.read_text())
    decision["delta_qlora"]["compatible_failures"] = 3
    decision["decision_sha256"] = canonical_hash(
        {key: value for key, value in decision.items() if key != "decision_sha256"}
    )
    assert any("eligibility" in error for error in validate_decision(decision))


def test_receipt_rejects_report_count_drift(tmp_path: Path) -> None:
    run = tmp_path / "run"
    raw = Path("artifacts/catalog-maintenance-probe-v1")
    for source in [raw / "report.json", raw / "worker.stderr.log"]:
        target = run / source.relative_to(raw)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    for source in (raw / "tasks").glob("*/attempts.json"):
        target = run / source.relative_to(raw)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    report = json.loads((run / "report.json").read_text())
    report["decision"]["counts"]["semantic_correct"] = 8
    (run / "report.json").write_text(json.dumps(report))
    with pytest.raises(EvidenceError, match="report counts"):
        build_evaluation_receipt(run_dir=run)


def test_receipt_rejects_attempt_text_hash_drift(tmp_path: Path) -> None:
    run = tmp_path / "run"
    raw = Path("artifacts/catalog-maintenance-probe-v1")
    for source in [raw / "report.json", raw / "worker.stderr.log"]:
        target = run / source.relative_to(raw)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    for source in (raw / "tasks").glob("*/attempts.json"):
        target = run / source.relative_to(raw)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    attempts_path = run / "tasks/author-enum3/attempts.json"
    attempts = json.loads(attempts_path.read_text())
    attempts[0]["text"] += "tamper"
    attempts_path.write_text(json.dumps(attempts))
    with pytest.raises(EvidenceError, match="attempt text hash drift"):
        build_evaluation_receipt(run_dir=run)


def test_receipt_rejects_any_additional_run_output(tmp_path: Path) -> None:
    run = tmp_path / "run"
    raw = Path("artifacts/catalog-maintenance-probe-v1")
    for source in [raw / "report.json", raw / "worker.stderr.log"]:
        target = run / source.relative_to(raw)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    for source in (raw / "tasks").glob("*/attempts.json"):
        target = run / source.relative_to(raw)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    (run / "unexpected-output.json").write_text("{}")
    with pytest.raises(EvidenceError, match="exact ten-file evidence roster"):
        build_evaluation_receipt(run_dir=run)


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False
