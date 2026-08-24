from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from metis_model1 import catalog_maintenance_successor as successor
from metis_model1 import catalog_maintenance_successor_evidence as evidence


def _sha_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(evidence.canonical_bytes(value) + b"\n")


def _score(*, passed: bool = True) -> dict[str, Any]:
    return {
        "semantic_correct": int(passed),
        "critical_failure": 0,
        "invented_values": 0,
        "legacy_inline": 0,
        "retrieval_error": 0,
        "skeleton_match": passed,
        "required_missing": [],
        "forbidden_hits": [],
        "retrieval_error_text": None,
    }


def _make_run(root: Path, *, passed: bool = True) -> tuple[Path, Path, Path]:
    _manifest, _schema, cases = successor.load_probe_contract()
    run = root / evidence.RUN_RELATIVE
    tasks = [
        {
            "case_id": case["case_id"],
            "root_id": case["provenance"]["semantic_root"],
        }
        for case in cases
    ]
    freeze: dict[str, Any] = {
        "status": "frozen_before_model_output",
        "model_outputs_observed": False,
        "training_authorized": False,
        "run_dir": evidence.RUN_RELATIVE,
        "preimage_commit": "a" * 40,
        "preimage_tree": "b" * 40,
        "model": {"family": "Qwen3.8", "adapter_enabled": False, "temperature": 0, "seed": 17},
        "tasks": tasks,
    }
    freeze["freeze_sha256"] = evidence.canonical_hash(freeze)
    freeze_path = root / evidence.FREEZE_RELATIVE
    _write_json(freeze_path, freeze)

    observations: list[dict[str, Any]] = []
    for case in cases:
        text = f"generated-{case['case_id']}"
        score = _score(passed=passed)
        attempt = {
            "attempt": 0,
            "text": text,
            "text_sha256": _sha_text(text),
            "receipt_sha256": None,
            "score": score,
        }
        _write_json(run / "tasks" / case["case_id"] / "attempts.json", [attempt])
        observations.append(
            {
                "case_id": case["case_id"],
                "root_id": case["provenance"]["semantic_root"],
                **score,
            }
        )
    report = {
        "schema_version": 1,
        "status": "complete",
        "head": "c" * 40,
        "tree": "d" * 40,
        "freeze_sha256": freeze["freeze_sha256"],
        "observations": observations,
        "decision": successor.gate_arithmetic(observations),
        "model_outputs_observed": True,
        "training_authorized": False,
    }
    _write_json(run / "report.json", report)
    (run / "worker.stderr.log").write_bytes(b"")
    return run, freeze_path, root / evidence.EVALUATION_RELATIVE


def test_green_run_projects_to_redacted_no_retrain_receipt_and_decision(tmp_path: Path) -> None:
    run, freeze, evaluation_path = _make_run(tmp_path)

    receipt = evidence.build_evaluation_receipt(
        root=tmp_path, run_dir=run, freeze_path=freeze, verify_repository=False
    )
    _write_json(evaluation_path, receipt)
    decision = evidence.build_decision(receipt, evaluation_path=evaluation_path, root=tmp_path)

    assert receipt["policy"]["verdict"] == "NO_RETRAIN_PROMPT_CURE"
    assert receipt["counts"]["semantic_correct"] == 8
    assert not evidence._contains_raw_key(receipt)
    assert decision["status"] == "NO_RETRAIN_PROMPT_CURE"
    assert all(
        decision[key] is False
        for key in (
            "training_authorized",
            "auto_qlora_authorized",
            "promotion_claim",
            "accuracy_claim",
        )
    )
    assert evidence.validate_evaluation_receipt(receipt, root=tmp_path, freeze_path=freeze) == []
    assert (
        evidence.validate_decision(decision, root=tmp_path, evaluation_path=evaluation_path) == []
    )


def test_failure_is_diagnose_but_never_training(tmp_path: Path) -> None:
    run, freeze, evaluation_path = _make_run(tmp_path, passed=False)

    receipt = evidence.build_evaluation_receipt(
        root=tmp_path, run_dir=run, freeze_path=freeze, verify_repository=False
    )
    _write_json(evaluation_path, receipt)
    decision = evidence.build_decision(receipt, evaluation_path=evaluation_path, root=tmp_path)

    assert receipt["policy"]["verdict"] == "DIAGNOSE"
    assert decision["status"] == "DIAGNOSE"
    assert decision["training_authorized"] is False


def test_evidence_rejects_extra_output_symlink_and_hardlink(tmp_path: Path) -> None:
    run, freeze, _evaluation_path = _make_run(tmp_path)
    (run / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(evidence.SuccessorEvidenceError, match="exact ten-file"):
        evidence.build_evaluation_receipt(
            root=tmp_path, run_dir=run, freeze_path=freeze, verify_repository=False
        )
    (run / "unexpected.json").unlink()

    os.symlink(run / "report.json", run / "linked-report.json")
    with pytest.raises(evidence.SuccessorEvidenceError, match="non-regular"):
        evidence.build_evaluation_receipt(
            root=tmp_path, run_dir=run, freeze_path=freeze, verify_repository=False
        )
    (run / "linked-report.json").unlink()

    os.link(run / "report.json", run / "hard-linked-report.json")
    with pytest.raises(evidence.SuccessorEvidenceError, match="non-regular|singly linked"):
        evidence.build_evaluation_receipt(
            root=tmp_path, run_dir=run, freeze_path=freeze, verify_repository=False
        )


def test_evidence_rejects_attempt_hash_score_and_report_decision_laundering(tmp_path: Path) -> None:
    run, freeze, _evaluation_path = _make_run(tmp_path)
    attempts_path = run / "tasks" / "author-audience-enum5" / "attempts.json"
    attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
    attempts[0]["text"] += " tampered"
    _write_json(attempts_path, attempts)
    with pytest.raises(evidence.SuccessorEvidenceError, match="text hash drift"):
        evidence.build_evaluation_receipt(
            root=tmp_path, run_dir=run, freeze_path=freeze, verify_repository=False
        )

    run, freeze, _evaluation_path = _make_run(tmp_path / "decision")
    report_path = run / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["decision"]["counts"]["semantic_correct"] = 7
    _write_json(report_path, report)
    with pytest.raises(evidence.SuccessorEvidenceError, match="decision does not recompute"):
        evidence.build_evaluation_receipt(
            root=tmp_path / "decision",
            run_dir=run,
            freeze_path=freeze,
            verify_repository=False,
        )


def test_validators_reject_rehashed_raw_output_and_decision_drift(tmp_path: Path) -> None:
    run, freeze, evaluation_path = _make_run(tmp_path)
    receipt = evidence.build_evaluation_receipt(
        root=tmp_path, run_dir=run, freeze_path=freeze, verify_repository=False
    )
    receipt["roster"]["cases"][0]["final_score"]["semantic_correct"] = 0
    receipt["evaluation_sha256"] = evidence.canonical_hash(
        {key: value for key, value in receipt.items() if key != "evaluation_sha256"}
    )
    assert any(
        "verdict" in error or "counts" in error
        for error in evidence.validate_evaluation_receipt(
            receipt, root=tmp_path, freeze_path=freeze
        )
    )

    receipt = evidence.build_evaluation_receipt(
        root=tmp_path, run_dir=run, freeze_path=freeze, verify_repository=False
    )
    receipt["roster"]["cases"][0]["final_score"]["skeleton_match"] = False
    receipt["counts"]["skeleton_match"] = 7
    receipt["evaluation_sha256"] = evidence.canonical_hash(
        {key: value for key, value in receipt.items() if key != "evaluation_sha256"}
    )
    assert any(
        "green score is inconsistent" in error
        for error in evidence.validate_evaluation_receipt(
            receipt, root=tmp_path, freeze_path=freeze
        )
    )

    receipt = evidence.build_evaluation_receipt(
        root=tmp_path, run_dir=run, freeze_path=freeze, verify_repository=False
    )
    _write_json(evaluation_path, receipt)
    decision = evidence.build_decision(receipt, evaluation_path=evaluation_path, root=tmp_path)
    decision["training_authorized"] = True
    decision["decision_sha256"] = evidence.canonical_hash(
        {key: value for key, value in decision.items() if key != "decision_sha256"}
    )
    assert any(
        "authority" in error
        for error in evidence.validate_decision(
            decision, root=tmp_path, evaluation_path=evaluation_path
        )
    )


def test_write_evidence_refuses_to_overwrite_terminal_outputs(tmp_path: Path) -> None:
    _run, _freeze, evaluation_path = _make_run(tmp_path)
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    evaluation_path.write_text("{}", encoding="utf-8")

    with pytest.raises(evidence.SuccessorEvidenceError, match="partial.*invalid"):
        evidence.write_evidence(root=tmp_path, verify_repository=False)


def test_write_evidence_recovers_a_valid_partial_evaluation_receipt_only(
    tmp_path: Path,
) -> None:
    run, freeze, evaluation_path = _make_run(tmp_path)
    evaluation = evidence.build_evaluation_receipt(
        root=tmp_path, run_dir=run, freeze_path=freeze, verify_repository=False
    )
    _write_json(evaluation_path, evaluation)
    decision = evidence.build_decision(evaluation, evaluation_path=evaluation_path, root=tmp_path)
    rebuilt_evaluation, rebuilt_decision = evidence.write_evidence(
        root=tmp_path, verify_repository=False
    )

    assert rebuilt_evaluation == evaluation
    assert rebuilt_decision == decision
    assert evidence.verify_evidence(root=tmp_path) == (evaluation, decision)


def test_write_evidence_rejects_a_decision_without_its_evaluation(tmp_path: Path) -> None:
    run, freeze, evaluation_path = _make_run(tmp_path)
    evaluation = evidence.build_evaluation_receipt(
        root=tmp_path, run_dir=run, freeze_path=freeze, verify_repository=False
    )
    _write_json(evaluation_path, evaluation)
    decision = evidence.build_decision(evaluation, evaluation_path=evaluation_path, root=tmp_path)
    _write_json(tmp_path / evidence.DECISION_RELATIVE, decision)
    evaluation_path.unlink()

    with pytest.raises(evidence.SuccessorEvidenceError, match="without its evaluation"):
        evidence.write_evidence(root=tmp_path, verify_repository=False)


def test_terminal_verify_is_receipt_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_run(tmp_path)
    evaluation, decision = evidence.write_evidence(root=tmp_path, verify_repository=False)

    def forbidden_rebuild(**_kwargs):
        raise AssertionError("terminal verify reopened ignored attempts")

    monkeypatch.setattr(evidence, "build_evaluation_receipt", forbidden_rebuild)
    assert evidence.verify_evidence(root=tmp_path) == (evaluation, decision)
